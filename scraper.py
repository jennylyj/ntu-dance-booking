import time  # <--- 新增這一行在最上面
import json  # <--- 確保也有這個

import requests
import urllib3
import sqlite3
import pandas as pd
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

# 忽略 SSL 警告
urllib3.disable_warnings()

# 場地對照表
VENUES = {
    '技擊室A': '107',
    '技擊室B': '108',
    '技擊室C': '109',
    '舊體': '80',
    '韻律': '87'
}

DB_NAME = "ntu_venues.db"

def init_db():
    """初始化資料庫，如果不存在則建立表格"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 建立表格：記錄場地、日期、小時、狀態、預約者、最後更新時間
    c.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue_name TEXT,
            venue_id TEXT,
            date TEXT,
            hour INTEGER,
            status TEXT,
            booker_name TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(venue_id, date, hour)
        )
    ''')
    conn.commit()
    conn.close()

def get_sunday_timestamp(week_offset=0):
    """計算指定週次週日的 timestamp (SDMK)"""
    tw_tz = timezone(timedelta(hours=8))
    today = datetime.now(tw_tz)
    # 找出本週日 (如果是週日，就是今天；否則往前推)
    # isoweekday: 1(Mon)-7(Sun)
    weekday = today.isoweekday()
    days_to_sunday = 0 if weekday == 7 else weekday
    
    this_sunday = today - timedelta(days=days_to_sunday)
    # 加上週次偏移 (offset=1 表示下週)
    target_sunday = this_sunday + timedelta(weeks=week_offset)
    
    # 設定為當天 00:00:00
    sunday_midnight = datetime(target_sunday.year, target_sunday.month, target_sunday.day, 0, 0, 0, tzinfo=tw_tz)
    
    sdmk = int(sunday_midnight.timestamp())
    edmk = int((sunday_midnight + timedelta(days=6)).timestamp())
    
    return sdmk, edmk, sunday_midnight

def fetch_venue_data(venue_name, venue_id, weeks_to_scrape=1):
    """爬取特定場地的資料"""
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest'
    }

    # 1. 進入主頁面抓取 EnV
    try:
        url_main = f"https://rent.pe.ntu.edu.tw/venues/?K={venue_id}"
        r_main = session.get(url_main, headers=headers, verify=False, timeout=10)
        soup_main = BeautifulSoup(r_main.text, 'html.parser')
        sk_elem = soup_main.find('textarea', {'name': 'SK'})
        if not sk_elem:
            return f"❌ {venue_name}: 找不到 EnV 金鑰"
        env = sk_elem.get_text().strip()
    except Exception as e:
        return f"❌ {venue_name}: 連線錯誤 {e}"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # 2. 針對每一週發送 API 請求
    for i in range(weeks_to_scrape):
        sdmk, edmk, start_date_obj = get_sunday_timestamp(week_offset=i)
        
        api_url = "https://rent.pe.ntu.edu.tw/__/f/Schedule.php"
        data = {
            'VenuesSN': venue_id,
            'OrderSource': 'undefined',
            'BookingType': 'undefined',
            'Booking': 'N',
            'OrderSN': 'undefined',
            'OrderType': 'D',
            'SDMK': sdmk,
            'EDMK': edmk,
            'ViewStatus': 'undefined',
            'EnV': env
        }

        try:
            # 加上 timeout 避免卡死
            r_api = session.post(api_url, headers=headers, data=data, verify=False, timeout=15)
            
            # 檢查 HTTP 狀態碼
            if r_api.status_code != 200:
                print(f"⚠️ {venue_name} 第 {i} 週請求失敗 (Status: {r_api.status_code})")
                continue

            try:
                json_data = r_api.json()
            except json.JSONDecodeError:
                # 這裡就是抓到 "Expecting value" 錯誤的地方
                # 印出回傳的前 100 個字，看看伺服器到底回傳了什麼鬼
                print(f"⚠️ {venue_name} 第 {i} 週回傳了非 JSON 資料: {r_api.text[:100]}")
                continue

            # 取得 HTML 表格 (有的時候在 ScheduleList，有的時候在 T)
            html_table = json_data.get('ScheduleList', '') or json_data.get('T', '')
            
            if html_table:
                parse_and_save(c, html_table, venue_name, venue_id, start_date_obj)
            else:
                print(f"⚠️ {venue_name} 第 {i} 週沒有課表資料")

            # 【關鍵】每抓完一週，休息 1 秒，避免被伺服器封鎖
            time.sleep(1)
            
        except Exception as e:
            print(f"Error scraping {venue_name} week {i}: {e}")

    conn.commit()
    conn.close()
    return f"✅ {venue_name}: 資料更新完成"

def parse_and_save(cursor, html, venue_name, venue_id, start_date_obj):
    """解析 HTML 並存入 DB (具備記憶力版)"""
    soup = BeautifulSoup(html, 'html.parser')
    day_cols = soup.find_all('div', class_='D')

    for day_idx, day_col in enumerate(day_cols):
        current_date = start_date_obj + timedelta(days=day_idx)
        date_str = current_date.strftime("%Y-%m-%d")

        # 【記憶變數】用來記住跨時段的預約者名稱
        # 每天開始時，先清空記憶
        current_booker_name = ""

        slots = day_col.find_all(['a', 'div'], class_='S')
        
        for slot in slots:
            # 1. 解析時間
            time_div = slot.find('div', class_='SText')
            if not time_div: continue
            
            time_text = time_div.get_text(strip=True) # "08 ~ 09"
            try:
                start_hour = int(time_text.split('~')[0].strip())
            except ValueError: continue

            # 2. 判斷狀態與處理記憶
            status = "可預約"
            booker_name = ""

            if slot.name == 'a':
                # --- 狀況 A：可預約 ---
                # 遇到空位，清空記憶
                current_booker_name = ""
                status = "可預約"
            
            elif slot.name == 'div':
                # --- 狀況 B：已預約 ---
                status = "已預約"
                
                # 試著找看看有沒有 "EventName" (這是台大系統記錄名稱的標準標籤)
                event_div = slot.find('div', class_='EventName')
                
                if event_div:
                    # B-1: 這一格是「頭」，有寫名字
                    # 更新記憶
                    current_booker_name = event_div.get_text(strip=True)
                    booker_name = current_booker_name
                
                else:
                    # B-2: 這一格是「身體」，裡面沒寫名字
                    # 嘗試用去背法檢查是否有其他文字 (例如有些沒包在 EventName 裡)
                    full_text = slot.get_text(strip=True)
                    raw_text = full_text.replace(time_text, "").strip()
                    
                    if raw_text:
                        # 如果有殘留文字，就用它當名字，並更新記憶
                        current_booker_name = raw_text
                        booker_name = current_booker_name
                    else:
                        # 如果真的全空，就使用「記憶中」的名字
                        booker_name = current_booker_name

            # 3. 存入資料庫
            # 這裡我們不需要再用 range 迴圈去自動長出時段了，
            # 因為台大的 HTML 結構其實每一小時都有一個 div (只是有的有字，有的沒字)
            # 我們只要順著 HTML 的格子一個一個存進去就好
            
            cursor.execute('''
                INSERT OR REPLACE INTO bookings (venue_name, venue_id, date, hour, status, booker_name, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (venue_name, venue_id, date_str, start_hour, status, booker_name))

# 測試用：直接執行此檔案會初始化 DB
if __name__ == "__main__":
    init_db()
    print("資料庫初始化完成")