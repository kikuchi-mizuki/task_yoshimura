#!/usr/bin/env python3
"""
現在認証中のGoogleアカウント情報を確認するスクリプト
使用方法: python check_google_account.py <LINE_USER_ID>
"""

import sys
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

def list_all_users():
    """認証済みユーザーの一覧を取得"""
    db_helper = DBHelper()
    user_ids = db_helper.get_all_user_ids()
    return user_ids

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python check_google_account.py <LINE_USER_ID>")
        print("\n認証済みユーザー一覧:")
        users = list_all_users()
        if users:
            for user_id in users:
                print(f"  - {user_id}")
        else:
            print("  認証済みユーザーがいません")
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

