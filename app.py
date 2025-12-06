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
weeks_to_scrape = st.sidebar.slider("抓取未來幾週？", 1, 25, 20)
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

# 【更新功能 2】新增檢視模式選擇
view_mode = st.sidebar.radio(
    "檢視模式",
    ("週曆模式 (看一週7天)", "星期模式 (看連五週)")
)

weekday_map = {"週日":0, "週一":1, "週二":2, "週三":3, "週四":4, "週五":5, "週六":6}
target_weekday_idx = 0

# 如果選擇星期模式，顯示下拉選單
if view_mode == "星期模式 (看連五週)":
    selected_weekday_str = st.sidebar.selectbox("選擇要檢查的星期", list(weekday_map.keys()), index=1) # 預設週一
    target_weekday_idx = weekday_map[selected_weekday_str]

show_mode = st.sidebar.radio(
    "顯示模式",
    ("顯示預約者 (若滿)", "僅顯示狀態 (可/不可)", "只看空場地")
)

# ==========================================
# 4. 主頁面 (Main Area)
# ==========================================
st.title("💃 台大熱舞社 場地協尋系統")

st.markdown("""
        <small>
        <b>圖例：</b> 🟢 可預約 | 🔴 已被預約 | ⚫ 場地不開放<br>
        若顯示空白，代表資料庫中無該時段紀錄（可能是該場地尚未開放該時段）。
        developed by 李昀臻 version 2025.12
        </small>
        """, unsafe_allow_html=True)

# --- 日期導航欄 (Navigation) ---
# 計算目前顯示的週次範圍
base_sunday = get_base_sunday()
current_sunday = base_sunday + timedelta(weeks=st.session_state['week_offset'])
current_saturday = current_sunday + timedelta(days=6)

# 根據模式決定要顯示哪些日期 (dates)
target_dates = []

if view_mode == "週曆模式 (看一週7天)":
    # 原本的邏輯：從該週日開始，連續 7 天
    target_dates = [current_sunday + timedelta(days=i) for i in range(7)]
    title_text = f"📅 {target_dates[0].strftime('%Y-%m-%d')} ~ {target_dates[-1].strftime('%Y-%m-%d')}"
    
else:
    # 新的邏輯：從該週的「特定星期」開始，往後抓 5 個相同的星期
    # 先算出該週的那個星期幾是哪一天
    start_weekday_date = current_sunday + timedelta(days=target_weekday_idx)
    target_dates = [start_weekday_date + timedelta(weeks=i) for i in range(5)]
    title_text = f"📅 {selected_weekday_str}特輯 ({target_dates[0].strftime('%m/%d')} ~ {target_dates[-1].strftime('%m/%d')})"


# 使用三欄位佈局：[上週] [標題] [下週]
col_prev, col_date, col_next = st.columns([1, 4, 1])

with col_prev:
    # 根據模式不同，按鈕的移動跨度也可以微調，這裡維持一週一週跳比較直覺
    if st.button("◀ 往前回推", use_container_width=True):
        st.session_state['week_offset'] -= 1
        st.rerun()

with col_next:
    if st.button("往後推進 ▶", use_container_width=True):
        st.session_state['week_offset'] += 1
        st.rerun()

with col_date:
    st.markdown(f"<h3 style='text-align: center; margin: 0;'>{title_text}</h3>", unsafe_allow_html=True)
    
    # 顯示目前是「本週」還是「未來第N週」
    offset = st.session_state['week_offset']
    label = "(本週)" if offset == 0 else (f"(未來 +{offset} 週)" if offset > 0 else f"(過去 {abs(offset)} 週)")
    st.markdown(f"<div style='text-align: center; color: gray;'>起始點：{label}</div>", unsafe_allow_html=True)

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
    # 1. 從資料庫抓取資料 (抓取範圍：最小日期 ~ 最大日期)
    min_date = target_dates[0].strftime('%Y-%m-%d')
    max_date = target_dates[-1].strftime('%Y-%m-%d')
    df = get_data(selected_venues, min_date, max_date)
    
    # 2. 準備顯示用的 DataFrame
    hours = range(8, 23) # 8:00 到 22:00

    # 設定欄位名稱
    if view_mode == "週曆模式 (看一週7天)":
        col_headers = [f"{d.strftime('%m/%d')}\n({list(weekday_map.keys())[d.isoweekday()%7]})" for d in target_dates]
    else:
        # 星期模式：欄位是日期，但括號內不用再寫星期幾(因為都一樣)，改寫「第幾週」比較清楚
        col_headers = [f"{d.strftime('%Y-%m-%d')}" for i, d in enumerate(target_dates)]

    # 建立空表格
    df_display = pd.DataFrame(
        {col: [""] * len(hours) for col in col_headers}, 
        index=[f"{h:02d}:00" for h in hours]
    )
    

    if df.empty:
        # 如果沒資料，顯示提示
        st.info(f"⚠️ 資料庫中沒有 {min_date} 到 {max_date} 的資料。")
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

        # 說明文字
        if view_mode == "星期模式 (看連五週)":
            st.info(f"💡 目前顯示的是連續 5 週的 **{selected_weekday_str}** 預約狀況。適合安排固定社課！")
        
        st.markdown("""
        <small>
        <b>圖例：</b> 🟢 可預約 | 🔴 已被預約 | ⚫ 場地不開放<br>
        若顯示空白，代表資料庫中無該時段紀錄（可能是該場地尚未開放該時段）。
        </small>
        """, unsafe_allow_html=True)
