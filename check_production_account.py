#!/usr/bin/env python3
"""
本番環境のデータベースからGoogleアカウント情報を取得するスクリプト
Railway CLI経由で実行するか、本番環境で直接実行
"""

import sys
import os
from calendar_service import GoogleCalendarService
from db import DBHelper

def get_google_account_info(line_user_id):
    """認証されているGoogleアカウントの情報を取得"""
    try:
        calendar_service = GoogleCalendarService()
        service = calendar_service._get_calendar_service(line_user_id)
        
        # primaryカレンダーの情報を取得
        calendar = service.calendarList().get(calendarId='primary').execute()
        
        # メールアドレスを取得（idまたはsummaryから）
        email = calendar.get('id', '')
        if '@' not in email:
            # idにメールアドレスが含まれていない場合はsummaryを確認
            email = calendar.get('summary', '')
        
        return {
            'email': email,
            'summary': calendar.get('summary', ''),
            'time_zone': calendar.get('timeZone', ''),
            'access_role': calendar.get('accessRole', '')
        }
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python check_production_account.py <LINE_USER_ID>")
        sys.exit(1)
    
    line_user_id = sys.argv[1]
    print(f"LINEユーザーID: {line_user_id}")
    print("Googleアカウント情報を取得中...")
    
    account_info = get_google_account_info(line_user_id)
    
    if account_info:
        print("\n✅ 認証されているGoogleアカウント:")
        print(f"📧 メールアドレス: {account_info['email']}")
        if account_info.get('time_zone'):
            print(f"🕐 タイムゾーン: {account_info['time_zone']}")
        if account_info.get('access_role'):
            print(f"🔐 アクセス権限: {account_info['access_role']}")
    else:
        print("❌ 認証情報の取得に失敗しました。")

