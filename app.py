import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import scraper  # 匯入我們剛寫好的 scraper.py

# 設定網頁標題與寬度
st.set_page_config(page_title="台大場地預約助手 by 李昀臻", layout="wide")

# ==========================================
# 1. 初始化狀態 (Session State)
# ==========================================
# 我們用 'week_offset' 來記住使用者現在看的是第幾週
# 0 = 本週, 1 = 下週, -1 = 上週
if 'week_offset' not in st.session_state:
    st.session_state['week_offset'] = 0

# ==========================================
# 2. 核心功能函式
# ==========================================
def get_data(venue_names, start_date, end_date):
    """從資料庫讀取指定日期範圍的資料"""
    conn = sqlite3.connect(scraper.DB_NAME)
    placeholders = ',' .join('?' for _ in venue_names)
    query = f'''
        SELECT venue_name, date, hour, status, booker_name 
        FROM bookings 
        WHERE venue_name IN ({placeholders})
        AND date BETWEEN ? AND ?
    '''
    # Flatten arguments
    args = list(venue_names) + [start_date, end_date]
    df = pd.read_sql_query(query, conn, params=args)
    conn.close()
    return df

# 計算「本週日」作為基準點
def get_base_sunday():
    today = datetime.now()
    weekday = today.isoweekday() # 1(Mon) - 7(Sun)
    days_to_sunday = 0 if weekday == 7 else weekday
    # 這裡定義：系統顯示的第一天是週日
    return today - timedelta(days=days_to_sunday)

# ==========================================
# 3. 側邊欄 (Sidebar)
# ==========================================
st.sidebar.title("🛠️ 控制面板")

st.sidebar.subheader("🔄 資料同步")
weeks_to_scrape = st.sidebar.slider("抓取未來幾週？", 1, 6, 2)
if st.sidebar.button("更新資料 (爬蟲)"):
    scraper.init_db() # 確保 DB 存在
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    total_venues = len(scraper.VENUES)
    for idx, (v_name, v_id) in enumerate(scraper.VENUES.items()):
        status_text.text(f"正在抓取：{v_name}...")
        # 這裡呼叫 scraper，抓取從「本週」開始往後數 N 週
        result = scraper.fetch_venue_data(v_name, v_id, weeks_to_scrape)
        progress_bar.progress((idx + 1) / total_venues)
        
    status_text.success("✅ 更新完成！")
    st.rerun() # 重新整理頁面

st.sidebar.markdown("---")

st.sidebar.subheader("📍 場地篩選")
all_venues = list(scraper.VENUES.keys())
# 預設選取所有場地，或只選舊體
selected_venues = st.sidebar.multiselect("顯示哪些場地？", all_venues, default=["舊體", "韻律"])

st.sidebar.subheader("👀 顯示設定")
show_mode = st.sidebar.radio(
    "顯示模式",
    ("顯示預約者 (若滿)", "僅顯示狀態 (可/不可)", "只看空場地")
)

# ==========================================
# 4. 主頁面 (Main Area)
# ==========================================
st.title("💃 台大熱舞社 場地協尋系統 by李昀臻 20251206")

# --- 日期導航欄 (Navigation) ---
# 計算目前顯示的週次範圍
base_sunday = get_base_sunday()
current_sunday = base_sunday + timedelta(weeks=st.session_state['week_offset'])
current_saturday = current_sunday + timedelta(days=6)

# 使用三欄位佈局：[上週] [標題] [下週]
col_prev, col_date, col_next = st.columns([1, 4, 1])

with col_prev:
    if st.button("◀ 上一週", use_container_width=True):
        st.session_state['week_offset'] -= 1
        st.rerun()

with col_next:
    if st.button("下一週 ▶", use_container_width=True):
        st.session_state['week_offset'] += 1
        st.rerun()

with col_date:
    # 漂亮的置中標題
    date_range_str = f"{current_sunday.strftime('%Y-%m-%d')} ~ {current_saturday.strftime('%Y-%m-%d')}"
    st.markdown(f"<h3 style='text-align: center; margin: 0;'>📅 {date_range_str}</h3>", unsafe_allow_html=True)
    
    # 顯示目前是「本週」還是「未來第N週」
    offset = st.session_state['week_offset']
    if offset == 0:
        week_label = "(本週)"
    elif offset > 0:
        week_label = f"(未來 +{offset} 週)"
    else:
        week_label = f"(過去 {abs(offset)} 週)"
    st.markdown(f"<div style='text-align: center; color: gray;'>{week_label}</div>", unsafe_allow_html=True)

# 快速回到本週按鈕 (如果切換太遠的話)
if st.session_state['week_offset'] != 0:
    if st.button("🏠 回到本週"):
        st.session_state['week_offset'] = 0
        st.rerun()

st.markdown("---")

# --- 顯示課表 ---

if not selected_venues:
    st.warning("👈 請在左側選擇至少一個場地！")
else:
    # 1. 從資料庫抓取該週資料
    df = get_data(selected_venues, current_sunday.strftime('%Y-%m-%d'), current_saturday.strftime('%Y-%m-%d'))
    
    # 2. 準備顯示用的 DataFrame
    hours = range(8, 23) # 8:00 到 22:00
    dates = [current_sunday + timedelta(days=i) for i in range(7)]
    weekdays_map = {0: '週日', 1: '週一', 2: '週二', 3: '週三', 4: '週四', 5: '週五', 6: '週六'}
    
    # 建立空的表格結構
    display_cols = [f"{d.strftime('%m/%d')}\n({weekdays_map[i]})" for i, d in enumerate(dates)]
    display_data = {col: [""] * len(hours) for col in display_cols}
    df_display = pd.DataFrame(display_data, index=[f"{h:02d}:00" for h in hours])

    if df.empty:
        # 如果沒資料，顯示提示
        st.info(f"⚠️ 目前資料庫沒有 {date_range_str} 的資料。")
        st.markdown("👉 **請按左側側邊欄的「更新資料」按鈕來爬取最新課表！**")
    else:
        # 3. 填入資料
        for date_idx, date_obj in enumerate(dates):
            d_str = date_obj.strftime('%Y-%m-%d')
            col_name = display_cols[date_idx]
            
            for h_idx, h in enumerate(hours):
                # 篩選這一格的資料
                cell_data = df[(df['date'] == d_str) & (df['hour'] == h)]
                
                cell_content = []
                for _, row in cell_data.iterrows():
                    v_name = row['venue_name']
                    status = row['status']
                    booker = row['booker_name']
                    
                    # 顯示邏輯
                    if show_mode == "只看空場地":
                        if status == "可預約":
                            cell_content.append(f"🟢{v_name}")
                    else:
                        if status == "可預約":
                             cell_content.append(f"🟢{v_name}")
                        elif status == "已預約":
                            if show_mode == "顯示預約者 (若滿)":
                                # 如果名字太長，截斷一下比較美觀
                                display_booker = (booker[:6] + '..') if len(booker) > 6 else booker
                                cell_content.append(f"🔴{v_name}: {display_booker}")
                            else:
                                cell_content.append(f"🔴{v_name}")
                        else:
                            cell_content.append(f"⚫{v_name}(X)")
                
                # 將同一格的多個場地資訊用換行符號接起來
                df_display.iat[h_idx, date_idx] = "\n".join(cell_content)

        # 4. 繪製表格
        # height 設定高一點讓它不需要一直捲動
        st.dataframe(df_display, use_container_width=True, height=600)
        
        st.markdown("""
        <small>
        <b>圖例：</b> 🟢 可預約 | 🔴 已被預約 | ⚫ 場地不開放<br>
        若顯示空白，代表資料庫中無該時段紀錄（可能是該場地尚未開放該時段）。
        </small>
        """, unsafe_allow_html=True)
