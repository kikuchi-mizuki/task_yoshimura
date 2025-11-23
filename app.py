import os
import logging
import base64
import json
import time
import re

# ログレベルを環境変数で制御
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL)

# Railway環境でcredentials.jsonを書き出す（Base64/プレーン両対応）
def write_credentials():
    val = os.environ.get("GOOGLE_CREDENTIALS_FILE")
    if not val:
        logging.warning("GOOGLE_CREDENTIALS_FILE環境変数が設定されていません")
        return False
    try:
        # Base64かプレーンJSONかを自動判定
        content = None
        try:
            decoded = base64.b64decode(val).decode("utf-8")
            json.loads(decoded)  # JSONとして解釈できるか確認
            content = decoded
            logging.info("credentials: Base64を検出してデコードしました")
        except Exception:
            json.loads(val)      # プレーンJSONか確認
            content = val
            logging.info("credentials: プレーンJSONとして検出しました")

        with open("credentials.json", "w") as f:
            f.write(content)
        
        # ファイル権限を600に設定（所有者のみ読み書き可能）
        os.chmod("credentials.json", 0o600)

        size = os.path.getsize("credentials.json")
        logging.info(f"credentials.jsonファイルが正常に作成されました (サイズ: {size} bytes)")
        return True
    except Exception as e:
        logging.error(f"credentials.jsonファイルの作成に失敗しました: {e}")
        import traceback
        logging.error(f"エラー詳細: {traceback.format_exc()}")
        raise

# credentials.jsonの作成を試行（エラー時はアプリ起動を継続）
try:
    write_credentials()
except Exception as e:
    logging.error(f"起動時にcredentials.jsonの作成に失敗しました: {e}")
    logging.warning("Google Calendar認証は使用できませんが、アプリケーションは起動します")

from flask import Flask, request, abort, render_template_string, redirect, make_response
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from line_bot_handler import LineBotHandler
from config import Config
from datetime import datetime
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from db import DBHelper
from werkzeug.middleware.proxy_fix import ProxyFix
from ai_service import AIService
from send_daily_agenda import send_daily_agenda

# ログ設定（環境変数でレベル制御）
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# セキュリティ設定
app.config.update(
    PREFERRED_URL_SCHEME="https",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ProxyFixを追加
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# セキュリティヘッダーを追加
@app.after_request
def set_security_headers(resp):
    # 本番のみ HSTS 推奨
    if os.getenv('ENV', 'production').lower() == 'production':
        resp.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains; preload'
    resp.headers['Content-Security-Policy'] = (
        "default-src 'none'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "form-action 'self' https://accounts.google.com; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    return resp

# 設定の検証
try:
    Config.validate_config()
    logger.info("設定の検証が完了しました")
except ValueError as e:
    logger.error(f"設定エラー: {e}")
    raise

# デバッグエンドポイントの有効化フラグ
ENABLE_DEBUG_ENDPOINTS = os.getenv('ENABLE_DEBUG_ENDPOINTS', 'false').lower() == 'true'

# LINEボットハンドラーを初期化
try:
    line_bot_handler = LineBotHandler()
    handler = line_bot_handler.get_handler()
    logger.info("LINEボットハンドラーの初期化が完了しました")
except Exception as e:
    logger.error(f"LINEボットハンドラーの初期化に失敗しました: {e}")
    raise

# セキュリティのためAPIキーなどの機密情報はログに出力しない

# DBヘルパーの初期化
db_helper = DBHelper()

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhookのコールバックエンドポイント"""
    signature = request.headers.get('X-Line-Signature')
    if not signature:
        logger.warning("X-Line-Signature ヘッダーがありません")
        abort(400)

    body = request.get_data(as_text=True)
    logger.debug("Request body (debug only): %s", body)

    try:
        # 署名を検証し、問題なければhandleに定義されている関数を呼び出す
        handler.handle(body, signature)
    except InvalidSignatureError:
        # 署名検証で失敗したときは例外をあげる
        logger.error("署名検証に失敗しました")
        abort(400)

    # 正常終了時は200を返す
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """テキストメッセージを処理"""
    try:
        logger.info(f"メッセージを受信: {event.message.text}")
        
        # メッセージを処理してレスポンスを取得
        response = line_bot_handler.handle_message(event)
        
        # LINEにメッセージを送信（reply_token期限対策、429対応）
        from linebot.exceptions import LineBotApiError
        max_retries = 3
        retry_delay = 1.5  # 秒
        
        for attempt in range(max_retries):
            try:
                line_bot_handler.line_bot_api.reply_message(
                    event.reply_token,
                    response
                )
                logger.info("メッセージの処理が完了しました")
                break
            except LineBotApiError as send_error:
                error_msg = str(send_error)
                logger.warning(f"メッセージ送信試行 {attempt + 1}/{max_retries} でエラー: {error_msg}")
                
                # 429 レート制限（status_codeで判定）
                if send_error.status_code == 429:
                    logger.info("レート制限を検出、2秒後にリトライします")
                    time.sleep(2.0)
                # SSLエラーの場合
                elif "SSL SYSCALL error" in error_msg or "EOF detected" in error_msg:
                    logger.info(f"SSLエラーを検出、{retry_delay}秒後にリトライします")
                    time.sleep(retry_delay)
                    retry_delay *= 1.5
                else:
                    if attempt < max_retries - 1:
                        time.sleep(1.0)
                        continue
                    else:
                        logger.error(f"最大リトライ回数に達しました: {send_error}")
                        raise send_error
            except Exception as send_error:
                error_msg = str(send_error)
                logger.warning(f"メッセージ送信試行 {attempt + 1}/{max_retries} でエラー: {error_msg}")
                # SSLエラーの場合
                if "SSL SYSCALL error" in error_msg or "EOF detected" in error_msg:
                    logger.info(f"SSLエラーを検出、{retry_delay}秒後にリトライします")
                    time.sleep(retry_delay)
                    retry_delay *= 1.5
                else:
                    if attempt < max_retries - 1:
                        time.sleep(1.0)
                        continue
                    else:
                        logger.error(f"最大リトライ回数に達しました: {send_error}")
                        raise send_error
        
    except Exception as e:
        logger.error(f"メッセージ処理でエラーが発生しました: {e}")
        # エラーが発生した場合はエラーメッセージを送信
        try:
            # エラーメッセージ送信時もリトライ機能を適用（簡略版）
            for attempt in range(2):
                try:
                    line_bot_handler.line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="申し訳ございません。エラーが発生しました。しばらく時間をおいて再度お試しください。")
                    )
                    logger.info("エラーメッセージの送信が完了しました")
                    break
                except Exception as reply_error:
                    logger.warning(f"エラーメッセージ送信試行 {attempt + 1}/2 でエラー: {reply_error}")
                    if attempt == 1:
                        logger.error(f"エラーメッセージの送信に失敗しました: {reply_error}")
                    else:
                        time.sleep(1)
        except Exception as reply_error:
            logger.error(f"エラーメッセージの送信に失敗しました: {reply_error}")

@app.route("/", methods=['GET'])
def index():
    """ヘルスチェック用エンドポイント"""
    return "LINE Calendar Bot is running!"

@app.route("/health", methods=['GET'])
def health():
    """ヘルスチェック用エンドポイント"""
    return {"status": "healthy", "service": "line-calendar-bot"}

@app.route("/test", methods=['GET'])
def test():
    """テスト用エンドポイント"""
    if not ENABLE_DEBUG_ENDPOINTS:
        return ("Not Found", 404)
    return {
        "message": "LINE Calendar Bot Test",
        "config": {
            "line_configured": bool(Config.LINE_CHANNEL_ACCESS_TOKEN and Config.LINE_CHANNEL_SECRET),
            "openai_configured": bool(Config.OPENAI_API_KEY),
            "google_configured": bool(os.path.exists('credentials.json'))
        }
    }

@app.route('/onetime_login', methods=['GET', 'POST'])
def onetime_login():
    """ワンタイムコード認証ページ"""
    if request.method == 'GET':
        # ワンタイムコード入力フォームを表示
        html = '''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Google Calendar 認証</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                .form-group { margin-bottom: 20px; }
                label { display: block; margin-bottom: 5px; font-weight: bold; }
                input[type="text"] { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; }
                button { background: #4285f4; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; }
                button:hover { background: #3367d6; }
                button:disabled { background: #ccc; cursor: not-allowed; }
                .error { color: red; margin-top: 10px; }
                .success { color: green; margin-top: 10px; }
            </style>
            <script>
                document.addEventListener('DOMContentLoaded', function() {
                    const form = document.querySelector('form');
                    const button = document.querySelector('button[type="submit"]');
                    
                    form.addEventListener('submit', function() {
                        button.disabled = true;
                        button.textContent = '認証中...';
                    });
                });
            </script>
        </head>
        <body>
            <h1>Google Calendar 認証</h1>
            <p>LINE BotでGoogle Calendarを利用するために認証が必要です。</p>
            <form method="POST">
                <div class="form-group">
                    <label for="code">ワンタイムコード:</label>
                    <input type="text" id="code" name="code" placeholder="8文字のコードを入力" required>
                </div>
                <button type="submit">認証を開始</button>
            </form>
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
            {% if success %}
            <div class="success">{{ success }}</div>
            {% endif %}
        </body>
        </html>
        '''
        return render_template_string(html, error=None, success=None)
    
    elif request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        logger.info(f"[DEBUG] 入力されたワンタイムコード: {code}")
        
        # ワンタイムコードの形式チェック（サーバ側バリデーション）
        if not re.fullmatch(r'[A-Z0-9]{8}', code):
            html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>認証エラー</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                    .error { color: red; margin: 20px 0; }
                    .back-link { margin-top: 20px; }
                </style>
            </head>
            <body>
                <h1>認証エラー</h1>
                <div class="error">
                    コードの形式が不正です。<br>
                    8文字の英数字コードを入力してください。
                </div>
                <div class="back-link">
                    <a href="/onetime_login">戻る</a>
                </div>
            </body>
            </html>
            '''
            return render_template_string(html)
        
        # ワンタイムコードを検証
        line_user_id = db_helper.verify_onetime_code(code)
        logger.info(f"[DEBUG] 検証結果: line_user_id={line_user_id}")
        if not line_user_id:
            html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>認証エラー</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                    .error { color: red; margin: 20px 0; }
                    .back-link { margin-top: 20px; }
                </style>
            </head>
            <body>
                <h1>認証エラー</h1>
                <div class="error">
                    無効なワンタイムコードです。<br>
                    コードが正しいか、有効期限が切れていないか確認してください。
                </div>
                <div class="back-link">
                    <a href="/onetime_login">戻る</a>
                </div>
            </body>
            </html>
            '''
            return render_template_string(html)
        
        try:
            # Google OAuth認証フローを開始
            SCOPES = ['https://www.googleapis.com/auth/calendar']
            
            # credentials.jsonの存在確認
            import os
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.jsonファイルが見つかりません")
            
            flow = Flow.from_client_secrets_file('credentials.json', scopes=SCOPES)
            # リダイレクトURIを環境変数から取得
            base_url = os.getenv('BASE_URL')
            if not base_url:
                raise ValueError("BASE_URL環境変数が設定されていません")
            # 末尾のスラッシュを削除してから結合
            base_url = base_url.rstrip('/')
            flow.redirect_uri = base_url + '/oauth2callback'
            
            # デバッグ用ログ（リダイレクトURIを表示）
            logger.info(f"[DEBUG] 設定されたリダイレクトURI: {flow.redirect_uri}")
            logger.info(f"[DEBUG] BASE_URL: {base_url}")
            
            # stateは引数を渡さず戻り値を使用
            auth_url, state = flow.authorization_url(
                access_type='offline',
                prompt='consent',
            )
            logger.info(f"[DEBUG] Google認証URL生成: auth_url={auth_url[:100]}...")
            logger.info(f"[DEBUG] OAuth state: {state}")
            
            # stateとline_user_idをDBに保存
            db_helper.save_oauth_state(state, line_user_id)
            logger.info(f"[DEBUG] OAuth stateをDBに保存完了")
            
            # ワンタイムコードを使用済みにマーク（リダイレクト直前に実行）
            db_helper.mark_onetime_used(code)
            logger.info(f"[DEBUG] ワンタイムコードを使用済みにマーク: {code}")
            
            logger.info(f"[DEBUG] Google認証ページにリダイレクト開始")
            response = redirect(auth_url)
            logger.info(f"[DEBUG] リダイレクトレスポンス: status_code={response.status_code}, location={response.headers.get('Location', 'None')}")
            return response
        except Exception as e:
            logging.error(f"Google OAuth認証エラー: {e}")
            import traceback
            logging.error(f"エラー詳細: {traceback.format_exc()}")
            html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>認証エラー</title>
                <meta charset="utf-8">
                <style>
                    body { font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto; padding: 20px; }
                    .error { color: red; margin: 20px 0; }
                </style>
            </head>
            <body>
                <h1>認証エラー</h1>
                <div class="error">
                    Google認証の初期化に失敗しました。<br>
                    しばらく時間をおいて再度お試しください。<br><br>
                    エラー詳細: {{ error_message }}
                </div>
            </body>
            </html>
            '''
            return render_template_string(html, error_message=str(e))

@app.route('/oauth2callback')
def oauth2callback():
    """Google OAuth認証コールバック"""
    from flask import make_response
    try:
        # stateから情報を取得
        state = request.args.get('state')
        record = db_helper.get_oauth_state(state)
        if not record:
            return make_response("認証セッションが無効です", 400)
        
        # 有効期限チェック
        from datetime import datetime, timezone
        if datetime.fromisoformat(record['expires_at']) < datetime.now(timezone.utc):
            return make_response("認証セッションが期限切れです", 400)
        
        line_user_id = record['line_user_id']
        
        # 新たにflowを生成
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        
        # credentials.jsonの存在確認
        import os
        if not os.path.exists('credentials.json'):
            raise FileNotFoundError("credentials.jsonファイルが見つかりません")
        
        flow = Flow.from_client_secrets_file('credentials.json', scopes=SCOPES)
        # リダイレクトURIを環境変数から取得
        base_url = os.getenv('BASE_URL')
        if not base_url:
            raise ValueError("BASE_URL環境変数が設定されていません")
        # 末尾のスラッシュを削除してから結合
        base_url = base_url.rstrip('/')
        flow.redirect_uri = base_url + '/oauth2callback'
        
        # デバッグ用ログ（リダイレクトURIを表示）
        logger.info(f"[DEBUG] oauth2callback リダイレクトURI: {flow.redirect_uri}")
        logger.info(f"[DEBUG] oauth2callback BASE_URL: {base_url}")
        
        # 認証コードを取得してトークンを交換（Flowはスコープ検証不要）
        logger.info(f"[DEBUG] fetch_token開始: request.url={request.url}")
        import warnings
        # Warningを無視する設定
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore')
            try:
                flow.fetch_token(authorization_response=request.url)
                logger.info(f"[DEBUG] fetch_token成功")
            except Warning as w:
                # oauthlibがWarningを例外としてraiseしている場合の処理
                logger.warning(f"[DEBUG] スコープ警告を無視して処理を継続: {w}")
                # Warning発生時は常に新規Flowを作成して再取得
                logger.info(f"[DEBUG] 新規Flowを作成して再取得")
                # 新しいFlowを作成
                flow2 = Flow.from_client_secrets_file('credentials.json', scopes=SCOPES)
                flow2.redirect_uri = flow.redirect_uri
                logger.info(f"[DEBUG] flow2作成完了、fetch_token開始")
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore')
                    flow2.fetch_token(authorization_response=request.url)
                logger.info(f"[DEBUG] flow2.fetch_token成功")
                logger.info(f"[DEBUG] flow2に置き換え")
                flow = flow2
        logger.info(f"[DEBUG] fetch_token完了")
        
        credentials = flow.credentials
        logger.info(f"[DEBUG] 認証情報取得完了: credentials={credentials is not None}")
        
        # トークンをJSON形式でDBに保存
        token_json = credentials.to_json()
        db_helper.save_google_token(line_user_id, token_json.encode('utf-8'))
        logger.info(f"[DEBUG] トークンをDBに保存完了（JSON形式）")
        
        # ワンタイムコードを使用済みに（line_user_idから消込）
        db_helper.mark_onetime_used_by_line_user(line_user_id)
        logger.info(f"[DEBUG] ワンタイムコードを使用済みにマーク完了")
        
        # OAuth stateを削除（使用済み）
        db_helper.delete_oauth_state(state)
        logger.info(f"[DEBUG] OAuth stateを削除完了")
        
        # 認証完了画面
        html = "<h2>Google認証が完了しました。LINEに戻って操作を続けてください。</h2>"
        logger.info(f"[DEBUG] 認証完了画面を返却")
        return make_response(html, 200)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return make_response(f"OAuth2コールバックエラー: {e}", 400)

@app.route('/debug/ai_test', methods=['GET', 'POST'])
def debug_ai_test():
    """AI抽出機能のデバッグ用エンドポイント"""
    if not ENABLE_DEBUG_ENDPOINTS:
        return ("Not Found", 404)
    from flask import render_template_string, request, jsonify
    
    if request.method == 'POST':
        try:
            text = request.form.get('text', '')
            if not text:
                return jsonify({"error": "テキストが入力されていません"})
            
            # AIサービスでテスト
            ai_service = AIService()
            result = ai_service.extract_dates_and_times(text)
            
            return jsonify({
                "input": text,
                "result": result,
                "success": True
            })
            
        except Exception as e:
            return jsonify({
                "error": str(e),
                "success": False
            })
    
    # GETリクエストの場合はテストフォームを表示
    test_form = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI抽出テスト</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .container { max-width: 600px; margin: 0 auto; }
            textarea { width: 100%; height: 100px; padding: 10px; margin: 10px 0; }
            button { background: #007bff; color: white; padding: 10px 20px; border: none; cursor: pointer; }
            .result { background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; }
            pre { white-space: pre-wrap; word-wrap: break-word; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>AI抽出機能テスト</h2>
            <form id="testForm">
                <label for="text">テストテキスト:</label><br>
                <textarea id="text" name="text" placeholder="例: ・7/10 9-10時&#10;・7/11 9-10時"></textarea><br>
                <button type="submit">テスト実行</button>
            </form>
            <div id="result" class="result" style="display: none;">
                <h3>結果:</h3>
                <pre id="resultContent"></pre>
            </div>
        </div>
        
        <script>
        document.getElementById('testForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const text = document.getElementById('text').value;
            const resultDiv = document.getElementById('result');
            const resultContent = document.getElementById('resultContent');
            
            resultContent.textContent = '処理中...';
            resultDiv.style.display = 'block';
            
            fetch('/debug/ai_test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'text=' + encodeURIComponent(text)
            })
            .then(response => response.json())
            .then(data => {
                resultContent.textContent = JSON.stringify(data, null, 2);
            })
            .catch(error => {
                resultContent.textContent = 'エラー: ' + error;
            });
        });
        </script>
    </body>
    </html>
    """
    return render_template_string(test_form)

@app.route('/api/send_daily_agenda', methods=['POST'])
def api_send_daily_agenda():
    import os
    from flask import request, jsonify
    secret_token = os.environ.get('DAILY_AGENDA_SECRET_TOKEN')
    req_token = request.headers.get('X-Auth-Token')
    if not secret_token or req_token != secret_token:
        return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
    try:
        send_daily_agenda()
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.exception("send_daily_agenda failed")
        return jsonify({'status': 'error', 'message': 'internal error'}), 500

@app.route('/api/debug_users', methods=['POST'])
def api_debug_users():
    if not ENABLE_DEBUG_ENDPOINTS:
        return ("Not Found", 404)
    import os
    from flask import request, jsonify
    secret_token = os.environ.get('DAILY_AGENDA_SECRET_TOKEN')
    req_token = request.headers.get('X-Auth-Token')
    if not secret_token or req_token != secret_token:
        return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
    from db import DBHelper
    db = DBHelper()
    c = db.conn.cursor()
    c.execute('SELECT line_user_id, LENGTH(google_token), created_at, updated_at FROM users')
    rows = c.fetchall()
    return jsonify({'users': rows})

@app.route('/api/debug_google_account', methods=['POST'])
def api_debug_google_account():
    """指定されたLINEユーザーIDのGoogleアカウント情報を取得"""
    if not ENABLE_DEBUG_ENDPOINTS:
        return ("Not Found", 404)
    import os
    from flask import request, jsonify
    secret_token = os.environ.get('DAILY_AGENDA_SECRET_TOKEN')
    req_token = request.headers.get('X-Auth-Token')
    if not secret_token or req_token != secret_token:
        return jsonify({'status': 'error', 'message': 'Forbidden'}), 403
    
    line_user_id = request.json.get('line_user_id') if request.is_json else request.form.get('line_user_id')
    if not line_user_id:
        return jsonify({'status': 'error', 'message': 'line_user_id is required'}), 400
    
    try:
        from calendar_service import GoogleCalendarService
        calendar_service = GoogleCalendarService()
        service = calendar_service._get_calendar_service(line_user_id)
        
        # primaryカレンダーの情報を取得
        calendar = service.calendarList().get(calendarId='primary').execute()
        
        # メールアドレスを取得（idまたはsummaryから）
        email = calendar.get('id', '')
        if '@' not in email:
            email = calendar.get('summary', '')
        
        return jsonify({
            'status': 'success',
            'line_user_id': line_user_id,
            'google_account': {
                'email': email,
                'summary': calendar.get('summary', ''),
                'time_zone': calendar.get('timeZone', ''),
                'access_role': calendar.get('accessRole', '')
            }
        })
    except Exception as e:
        logger.error(f"Googleアカウント情報取得エラー: {e}")
        import traceback
        return jsonify({
            'status': 'error',
            'message': str(e),
            'traceback': traceback.format_exc()
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("LINE Calendar Bot を起動しています...")
    
    # ネットワーク設定の確認
    import ssl
    import requests
    import urllib3
    logger.info(f"SSL バージョン: {ssl.OPENSSL_VERSION}")
    logger.info(f"Requests バージョン: {requests.__version__}")
    logger.info(f"urllib3 バージョン: {urllib3.__version__}")
    
    # Railwayはgunicornで起動するため、ローカル用途のみ
    app.run(debug=False, host='0.0.0.0', port=port) 