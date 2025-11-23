#!/usr/bin/env python3
"""
本番環境のデバッグエンドポイント経由でGoogleアカウント情報を取得するスクリプト
"""

import sys
import os
import requests
import json

def get_google_account_from_production(line_user_id, base_url, secret_token):
    """本番環境のデバッグエンドポイントからGoogleアカウント情報を取得"""
    url = f"{base_url}/api/debug_google_account"
    headers = {
        'X-Auth-Token': secret_token,
        'Content-Type': 'application/json'
    }
    data = {
        'line_user_id': line_user_id
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"リクエストエラー: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"レスポンス: {e.response.text}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python check_production_account_remote.py <LINE_USER_ID> [BASE_URL] [SECRET_TOKEN]")
        print("\n環境変数から取得する場合:")
        print("  BASE_URL: 本番環境のURL")
        print("  DAILY_AGENDA_SECRET_TOKEN: 認証トークン")
        sys.exit(1)
    
    line_user_id = sys.argv[1]
    base_url = sys.argv[2] if len(sys.argv) > 2 else os.getenv('BASE_URL')
    secret_token = sys.argv[3] if len(sys.argv) > 3 else os.getenv('DAILY_AGENDA_SECRET_TOKEN')
    
    if not base_url:
        print("❌ BASE_URLが設定されていません")
        print("   環境変数として設定するか、引数として指定してください")
        sys.exit(1)
    
    if not secret_token:
        print("❌ DAILY_AGENDA_SECRET_TOKENが設定されていません")
        print("   環境変数として設定するか、引数として指定してください")
        sys.exit(1)
    
    print(f"LINEユーザーID: {line_user_id}")
    print(f"本番環境URL: {base_url}")
    print("Googleアカウント情報を取得中...")
    
    result = get_google_account_from_production(line_user_id, base_url, secret_token)
    
    if result and result.get('status') == 'success':
        account = result.get('google_account', {})
        print("\n✅ 認証されているGoogleアカウント:")
        print(f"📧 メールアドレス: {account.get('email', 'N/A')}")
        if account.get('time_zone'):
            print(f"🕐 タイムゾーン: {account.get('time_zone')}")
        if account.get('access_role'):
            print(f"🔐 アクセス権限: {account.get('access_role')}")
    else:
        print("❌ 認証情報の取得に失敗しました。")
        if result:
            print(f"エラー: {result.get('message', 'Unknown error')}")
            if result.get('traceback'):
                print("\n詳細:")
                print(result['traceback'])

