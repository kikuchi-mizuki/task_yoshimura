#!/usr/bin/env python3
"""
デプロイ状況とGoogleアカウント情報を確認するスクリプト
"""

import requests
import json
import time
import sys

BASE_URL = 'https://task-bot-production.up.railway.app'
LINE_USER_ID = 'U6ba71c843562e6db5d8b58c5b895e5ed'

def check_endpoint():
    """エンドポイントの存在を確認"""
    try:
        # デバッグエンドポイントが有効か確認
        response = requests.get(f'{BASE_URL}/api/debug_google_account', timeout=10)
        if response.status_code == 404:
            return False, "デバッグエンドポイントが無効です（ENABLE_DEBUG_ENDPOINTS=falseの可能性）"
        elif response.status_code == 403:
            return True, "エンドポイントは存在します（認証が必要）"
        else:
            return True, f"エンドポイントは存在します（ステータス: {response.status_code}）"
    except Exception as e:
        return False, f"エラー: {e}"

def get_google_account(secret_token):
    """Googleアカウント情報を取得"""
    url = f'{BASE_URL}/api/debug_google_account'
    headers = {
        'X-Auth-Token': secret_token,
        'Content-Type': 'application/json'
    }
    data = {
        'line_user_id': LINE_USER_ID
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return {'error': 'エンドポイントが見つかりません。ENABLE_DEBUG_ENDPOINTS=trueに設定してください。'}
        elif e.response.status_code == 403:
            return {'error': '認証に失敗しました。DAILY_AGENDA_SECRET_TOKENを確認してください。'}
        else:
            return {'error': f'HTTPエラー: {e.response.status_code} - {e.response.text}'}
    except Exception as e:
        return {'error': f'エラー: {e}'}

if __name__ == "__main__":
    print(f"本番環境URL: {BASE_URL}")
    print(f"LINEユーザーID: {LINE_USER_ID}")
    print()
    
    # エンドポイントの確認
    print("1. エンドポイントの確認中...")
    exists, message = check_endpoint()
    print(f"   {message}")
    print()
    
    if not exists:
        print("⚠️ デバッグエンドポイントが有効になっていません。")
        print("   Railwayの環境変数で ENABLE_DEBUG_ENDPOINTS=true に設定してください。")
        sys.exit(1)
    
    # シークレットトークンの確認
    if len(sys.argv) < 2:
        print("❌ DAILY_AGENDA_SECRET_TOKENが必要です")
        print("   使用方法: python3 check_deploy_status.py <DAILY_AGENDA_SECRET_TOKEN>")
        sys.exit(1)
    
    secret_token = sys.argv[1]
    
    # Googleアカウント情報の取得
    print("2. Googleアカウント情報を取得中...")
    result = get_google_account(secret_token)
    
    if 'error' in result:
        print(f"❌ {result['error']}")
        sys.exit(1)
    
    if result.get('status') == 'success':
        account = result.get('google_account', {})
        print("\n✅ 認証されているGoogleアカウント:")
        print(f"📧 メールアドレス: {account.get('email', 'N/A')}")
        if account.get('time_zone'):
            print(f"🕐 タイムゾーン: {account.get('time_zone')}")
        if account.get('access_role'):
            print(f"🔐 アクセス権限: {account.get('access_role')}")
    else:
        print(f"❌ エラー: {result.get('message', 'Unknown error')}")
        if result.get('traceback'):
            print("\n詳細:")
            print(result['traceback'])

