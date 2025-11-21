import openai
from datetime import datetime, timedelta
from dateutil import parser
import re
import json
from config import Config
import calendar
import pytz

class AIServiceDebug:
    def __init__(self):
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        print(f"[DEBUG] AIServiceDebug初期化完了")
        print(f"[DEBUG] OpenAI API Key: {'設定済み' if Config.OPENAI_API_KEY else '未設定'}")
    
    def _get_jst_now_str(self):
        now = datetime.now(pytz.timezone('Asia/Tokyo'))
        return now.strftime('%Y-%m-%dT%H:%M:%S%z')
    
    def extract_dates_and_times(self, text):
        """テキストから日時を抽出し、タスクの種類を判定します（デバッグ版）"""
        print(f"\n[DEBUG] extract_dates_and_times開始")
        print(f"[DEBUG] 入力テキスト: {text}")
        
        try:
            now_jst = self._get_jst_now_str()
            print(f"[DEBUG] 現在時刻: {now_jst}")
            
            system_prompt = (
                f"あなたは予定とタスクを管理するAIです。\n"
                f"現在の日時（日本時間）は {now_jst} です。  \n"
                "【最重要】ユーザーの入力が箇条書き・改行・スペース・句読点で区切られている場合も、全ての時間帯・枠を必ず個別に抽出してください。\n"
                "この日時は、すべての自然言語の解釈において**常に絶対的な基準**としてください。  \n"
                "会話の流れや前回の入力に引きずられることなく、**毎回この現在日時を最優先にしてください。**\n"
                "\n"
                "あなたは日時抽出とタスク管理の専門家です。ユーザーのテキストを分析して、以下のJSON形式で返してください。\n\n"
                "分析ルール:\n"
                "1. 複数の日時がある場合は全て抽出\n"
                "2. 日本語の日付表現（今日、明日、来週月曜日など）を具体的な日付に変換\n"
                "3. 時間表現（午前9時、14時30分、9-10時、9時-10時、9:00-10:00など）を24時間形式に変換\n"
                "4. **タスクの種類を判定（重要）**:\n   - 日時のみ（タイトルや内容がない）場合は必ず「availability_check」（空き時間確認）\n   - 日時+タイトル/予定内容がある場合は「add_event」（予定追加）\n   - 例：「7/8 18時以降」→ availability_check（日時のみ）\n   - 例：「7/10 18:00〜20:00」→ availability_check（日時のみ）\n   - 例：「・7/10 9-10時\n・7/11 9-10時」→ availability_check（日時のみ複数）\n   - 例：「7/10 9-10時」→ availability_check（9:00〜10:00として抽出）\n   - 例：「7/10 9時-10時」→ availability_check（9:00〜10:00として抽出）\n   - 例：「7/10 9:00-10:00」→ availability_check（9:00〜10:00として抽出）\n   - 例：「明日の午前9時から会議を追加して」→ add_event（日時+予定内容）\n   - 例：「来週月曜日の14時から打ち合わせ」→ add_event（日時+予定内容）\n"
                "5. 自然言語の時間表現は必ず具体的な時刻範囲・日付範囲に変換してください。\n"
                "   例：'18時以降'→'18:00〜23:59'、'終日'→'00:00〜23:59'、'今日'→'現在時刻〜23:59'、'今日から1週間'→'今日〜7日後の23:59'。\n"
                "6. 箇条書き（・や-）、改行、スペース、句読点で区切られている場合も、すべての日時・時間帯を抽出してください。\n"
                "   例：'・7/10 9-10時\n・7/11 9-10時' → 2件の予定として抽出\n"
                "   例：'7/11 15:00〜16:00 18:00〜19:00' → 2件の予定として抽出\n"
                "   例：'7/12 終日' → 1件の終日予定として抽出\n"
                "7. 同じ日付の終日予定は1件だけ抽出してください。\n"
                "8. 予定タイトル（description）も必ず抽出してください。\n"
                "9. \"終日\"や\"00:00〜23:59\"の終日枠は、ユーザーが明示的に\"終日\"と書いた場合のみ抽出してください。\n"
                "10. 1つの日付に複数の時間帯（枠）が指定されている場合は、必ずその枠ごとに抽出してください。\n"
                "11. 同じ日に部分枠（例: 15:00〜16:00, 18:00〜19:00）がある場合は、その日付の終日枠（00:00〜23:59）は抽出しないでください。\n"
                "12. 複数の日時・時間帯が入力される場合、全ての時間帯をリストにし、それぞれに対して開始時刻・終了時刻をISO形式（例: 2025-07-11T15:00:00+09:00）で出力してください。\n"
                "13. 予定タイトル（会議名や打合せ名など）と、説明（議題や詳細、目的など）があれば両方抽出してください。\n"
                "14. 説明はタイトル以降の文や\"の件\"\"について\"などを優先して抽出してください。\n"
                "\n"
                "【出力例】\n"
                "空き時間確認の場合:\n"
                "{\n  \"task_type\": \"availability_check\",\n  \"dates\": [\n    {\n      \"date\": \"2025-07-08\",\n      \"time\": \"18:00\",\n      \"end_time\": \"23:59\"\n    }\n  ]\n}\n"
                "\n"
                "予定追加の場合:\n"
                "{\n  \"task_type\": \"add_event\",\n  \"dates\": [\n    {\n      \"date\": \"2025-07-14\",\n      \"time\": \"20:00\",\n      \"end_time\": \"20:30\",\n      \"title\": \"田中さんMTG\",\n      \"description\": \"新作アプリの件\"\n    }\n  ]\n}\n"
            )
            
            print(f"[DEBUG] システムプロンプト長: {len(system_prompt)}文字")
            
            print(f"[DEBUG] OpenAI API呼び出し開始...")
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.1
            )
            
            print(f"[DEBUG] OpenAI API呼び出し完了")
            print(f"[DEBUG] 使用モデル: {response.model}")
            print(f"[DEBUG] トークン使用量: {response.usage}")
            
            result = response.choices[0].message.content
            print(f"[DEBUG] 生のAIレスポンス: {result}")
            
            parsed = self._parse_ai_response(result)
            print(f"[DEBUG] パース結果: {parsed}")
            
            supplemented = self._supplement_times(parsed, text)
            print(f"[DEBUG] 補完後結果: {supplemented}")
            
            return supplemented
            
        except Exception as e:
            print(f"[DEBUG] エラー発生: {e}")
            return {"error": "イベント情報を正しく認識できませんでした。\n\n・日時を打つと空き時間を返します\n・予定を打つとカレンダーに追加します\n\n例：\n『明日の午前9時から会議を追加して』\n『来週月曜日の14時から打ち合わせ』"}
    
    def _parse_ai_response(self, response):
        """AIの応答をパースします"""
        print(f"[DEBUG] _parse_ai_response開始")
        print(f"[DEBUG] パース対象: {response}")
        
        try:
            # JSON部分を抽出
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                print(f"[DEBUG] 抽出されたJSON: {json_str}")
                parsed = json.loads(json_str)
                print(f"[DEBUG] パース成功: {parsed}")
                return parsed
            else:
                print(f"[DEBUG] JSON部分が見つかりません")
                return {"error": "AI応答のパースに失敗しました"}
        except Exception as e:
            print(f"[DEBUG] JSONパースエラー: {e}")
            return {"error": f"JSONパースエラー: {str(e)}"}
    
    def _supplement_times(self, parsed, original_text):
        """AIの出力でtimeやend_timeが空の場合に自然言語表現や状況に応じて自動補完する（デバッグ版）"""
        print(f"[DEBUG] _supplement_times開始")
        print(f"[DEBUG] 元テキスト: {original_text}")
        print(f"[DEBUG] パース済みデータ: {parsed}")
        
        from datetime import datetime, timedelta
        import re
        jst = pytz.timezone('Asia/Tokyo')
        now = datetime.now(jst)
        
        if not parsed or 'dates' not in parsed:
            print(f"[DEBUG] パースデータが不正: {parsed}")
            return parsed
            
        # --- 既存AI抽出の補完処理 ---
        allday_dates = set()
        new_dates = []
        
        for i, d in enumerate(parsed['dates']):
            print(f"[DEBUG] 処理中 {i+1}件目: {d}")
            phrase = d.get('description', '') or original_text
            
            # 終日
            if (not d.get('time') and not d.get('end_time')) or re.search(r'終日', phrase):
                d['time'] = '00:00'
                d['end_time'] = '23:59'
                print(f"[DEBUG] 終日として補完: {d}")
                if d.get('date') in allday_dates:
                    print(f"[DEBUG] 同じ日付の終日予定はスキップ: {d.get('date')}")
                    continue
                allday_dates.add(d.get('date'))
                
            # 18時以降
            elif re.search(r'(\d{1,2})時以降', phrase):
                m = re.search(r'(\d{1,2})時以降', phrase)
                if m:
                    d['time'] = f"{int(m.group(1)):02d}:00"
                    d['end_time'] = '23:59'
                    print(f"[DEBUG] 時以降として補完: {d}")
                    
            # 明日
            elif re.search(r'明日', phrase):
                d['date'] = (now + timedelta(days=1)).strftime('%Y-%m-%d')
                if not d.get('time'):
                    d['time'] = '08:00'
                if not d.get('end_time'):
                    d['end_time'] = '23:59'
                print(f"[DEBUG] 明日として補完: {d}")
                
            # 今日
            elif re.search(r'今日', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                if not d.get('time'):
                    d['time'] = now.strftime('%H:%M')
                if not d.get('end_time'):
                    d['end_time'] = '23:59'
                print(f"[DEBUG] 今日として補完: {d}")
                
            # 今日から1週間
            elif re.search(r'今日から1週間', phrase):
                d['date'] = now.strftime('%Y-%m-%d')
                d['end_date'] = (now + timedelta(days=6)).strftime('%Y-%m-%d')
                d['time'] = '00:00'
                d['end_time'] = '23:59'
                print(f"[DEBUG] 今日から1週間として補完: {d}")
                
            # end_timeが空
            elif d.get('time') and not d.get('end_time'):
                d['end_time'] = '23:59'
                print(f"[DEBUG] end_time補完: {d}")
            
            # 空き時間確認で時間が指定されていない場合、デフォルトで8:00〜23:59を設定
            if parsed.get('task_type') == 'availability_check':
                # 抽出された時間が現在時刻に近い場合（明示的な指定ではないと判断）、デフォルトを適用
                if d.get('time'):
                    try:
                        from datetime import datetime
                        extracted_time = datetime.strptime(d.get('time'), "%H:%M").time()
                        current_time = now.time()
                        # 現在時刻との差を計算（分単位）
                        time_diff = abs((extracted_time.hour * 60 + extracted_time.minute) - (current_time.hour * 60 + current_time.minute))
                        # 30分以内の差の場合は、明示的な指定ではないと判断してデフォルトを適用
                        if time_diff <= 30:
                            print(f"[DEBUG] 抽出された時間({d.get('time')})が現在時刻({current_time.strftime('%H:%M')})に近いため、デフォルトを適用")
                            d['time'] = '08:00'
                            d['end_time'] = '23:59'
                    except Exception as e:
                        print(f"[DEBUG] 時間比較エラー: {e}")
                
                if not d.get('time') or not d.get('end_time'):
                    # 終日（00:00〜23:59）の場合はそのまま
                    if d.get('time') == '00:00' and d.get('end_time') == '23:59':
                        pass  # 終日の場合はそのまま
                    else:
                        # 時間が指定されていない場合は8:00〜23:59をデフォルト設定
                        if not d.get('time'):
                            d['time'] = '08:00'
                        if not d.get('end_time'):
                            d['end_time'] = '23:59'
                        print(f"[DEBUG] 時間未指定のためデフォルト設定: {d.get('time')}〜{d.get('end_time')}")
                
            # title補完（空き時間確認の場合はタイトルを生成しない）
            if not d.get('title') or d['title'] == '':
                if d.get('description'):
                    d['title'] = d['description']
                elif parsed.get('task_type') == 'add_event':
                    # 予定追加の場合のみタイトルを生成
                    t = d.get('time', '')
                    e = d.get('end_time', '')
                    d['title'] = f"予定（{d.get('date', '')} {t}〜{e}）"
                print(f"[DEBUG] title補完: {d.get('title')}")
                
            new_dates.append(d)
            
        # --- ここから全日枠の除外 ---
        if len(new_dates) > 1:
            filtered = []
            for d in new_dates:
                if d.get('time') == '00:00' and d.get('end_time') == '23:59':
                    if any((d2.get('date') == d.get('date') and (d2.get('time') != '00:00' or d2.get('end_time') != '23:59')) for d2 in new_dates):
                        print(f"[DEBUG] 全日枠を除外: {d}")
                        continue
                filtered.append(d)
            new_dates = filtered
            
        # --- 正規表現で漏れた枠を補完 ---
        print(f"[DEBUG] 正規表現補完開始")
        
        # 例: 7/10 9-10時, 7/11 9:00-10:00, 7/12 15:00〜16:00, 7/10 9時-10時, 7/10 9:00-10:00
        pattern1 = r'(\d{1,2})/(\d{1,2})[\s　]*([0-9]{1,2}):?([0-9]{0,2})[\-〜~]([0-9]{1,2}):?([0-9]{0,2})'
        matches1 = re.findall(pattern1, original_text)
        print(f"[DEBUG] pattern1マッチ: {matches1}")
        
        for m in matches1:
            month, day, sh, sm, eh, em = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:{sm if sm else '00'}"
            end_time = f"{int(eh):02d}:{em if em else '00'}"
            
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern1で補完: {new_date_entry}")
                
        # 例: ・7/10 9-10時 などの箇条書きにも対応
        pattern2 = r'[・\-]\s*(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})-([0-9]{1,2})時'
        matches2 = re.findall(pattern2, original_text)
        print(f"[DEBUG] pattern2マッチ: {matches2}")
        
        for m in matches2:
            month, day, sh, eh = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:00"
            end_time = f"{int(eh):02d}:00"
            
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern2で補完: {new_date_entry}")
                
        # 追加: 日付+「9-10時」「9時-10時」「9:00-10:00」形式の抽出
        pattern3 = r'(\d{1,2})/(\d{1,2})\s*([0-9]{1,2})時?-([0-9]{1,2})時?'
        matches3 = re.findall(pattern3, original_text)
        print(f"[DEBUG] pattern3マッチ: {matches3}")
        
        for m in matches3:
            month, day, sh, eh = m
            year = now.year
            try:
                dt = datetime(year, int(month), int(day))
                if dt < now:
                    dt = datetime(year+1, int(month), int(day))
            except Exception:
                continue
            date_str = dt.strftime('%Y-%m-%d')
            start_time = f"{int(sh):02d}:00"
            end_time = f"{int(eh):02d}:00"
            
            if not any(d.get('date') == date_str and d.get('time') == start_time and d.get('end_time') == end_time for d in new_dates):
                new_date_entry = {
                    'date': date_str,
                    'time': start_time,
                    'end_time': end_time,
                    'description': ''
                }
                if parsed.get('task_type') == 'add_event':
                    new_date_entry['title'] = f"予定（{date_str} {start_time}〜{end_time}）"
                new_dates.append(new_date_entry)
                print(f"[DEBUG] pattern3で補完: {new_date_entry}")
                
        parsed['dates'] = new_dates
        print(f"[DEBUG] 最終結果: {parsed}")
        return parsed

# テスト用の関数
def test_debug_ai():
    """デバッグ版AIサービスをテスト"""
    print("=== デバッグ版AIサービステスト ===")
    
    try:
        ai_service = AIServiceDebug()
        
        # 問題のあるテストケース
        test_cases = [
            "・7/10 9-10時\n・7/11 9-10時",
            "7/10 9-10時",
            "7/10 9時-10時"
        ]
        
        for test_input in test_cases:
            print(f"\n{'='*50}")
            print(f"テスト入力: {test_input}")
            print(f"{'='*50}")
            
            result = ai_service.extract_dates_and_times(test_input)
            
            print(f"\n最終結果:")
            if 'dates' in result:
                for i, date_info in enumerate(result['dates'], 1):
                    print(f"  {i}. 日付: {date_info.get('date')}, 開始: {date_info.get('time')}, 終了: {date_info.get('end_time')}")
            else:
                print(f"  エラー: {result}")
                
    except Exception as e:
        print(f"テスト中にエラー: {e}")

if __name__ == "__main__":
    test_debug_ai() 