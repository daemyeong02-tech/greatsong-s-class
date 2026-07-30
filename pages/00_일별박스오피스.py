import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote

st.set_page_config(page_title="박스오피스 대시보드", layout="wide")
st.title("🎬 어제의 박스오피스")

# 비밀 금고에서 인증키 꺼내기 (코드에는 키를 적지 않는다)
KOBIS_KEY = st.secrets["KOBIS_KEY"]

KST = ZoneInfo("Asia/Seoul")
today_kst = datetime.now(KST).date()
default_date = today_kst - timedelta(days=1)

# 조회 날짜를 사용자가 고를 수 있게 (주말·공휴일 등 자료 없는 날 대비)
selected_date = st.date_input(
    "조회할 날짜",
    value=default_date,
    max_value=default_date,
)
target_dt = selected_date.strftime("%Y%m%d")
st.caption(f"조회 기준일: {selected_date.strftime('%Y-%m-%d')}")


@st.cache_data(ttl=3600)  # 1시간 캐시 — 같은 날짜 재요청 시 API 호출 절약
def fetch_box_office(target_dt: str, api_key: str) -> dict:
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    res = requests.get(url, params={"key": api_key, "targetDt": target_dt}, timeout=10)
    res.raise_for_status()
    return res.json()


@st.cache_data(ttl=86400)  # 영화 상세정보(장르·국가)는 거의 안 바뀌니 하루 캐시
def fetch_movie_info(movie_cd: str, api_key: str) -> dict:
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json"
    res = requests.get(url, params={"key": api_key, "movieCd": movie_cd}, timeout=10)
    res.raise_for_status()
    return res.json()


with st.spinner("박스오피스 정보를 불러오는 중..."):
    try:
        data = fetch_box_office(target_dt, KOBIS_KEY)
    except requests.exceptions.RequestException as e:
        st.error(f"KOBIS 서버에 연결할 수 없습니다: {e}")
        st.stop()

# KOBIS는 키가 틀려도 상태코드 200을 준다. 대신 faultInfo 상자가 온다.
if "faultInfo" in data:
    msg = data["faultInfo"].get("message", "알 수 없는 오류")
    st.error(f"인증키가 올바르지 않거나 요청이 잘못되었습니다. ({msg})")
    st.stop()

box_list = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
if not box_list:
    st.warning("그날 자료가 없습니다. 날짜를 하루 더 앞으로 옮겨 보세요.")
    st.stop()

df = pd.DataFrame(box_list)

# 글자로 온 숫자들을 진짜 숫자로 바꾸기 (이상값은 0으로 처리)
for col in ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

# 일별 박스오피스 응답엔 장르·국가가 없어서, 영화별 상세 API로 채워 넣는다
genres, nations = [], []
with st.spinner("영화 상세 정보를 불러오는 중..."):
    for movie_cd in df["movieCd"]:
        try:
            info = fetch_movie_info(movie_cd, KOBIS_KEY)
            m = info.get("movieInfoResult", {}).get("movieInfo", {})
            genre_list = m.get("genres", [])
            nation_list = m.get("nations", [])
            genres.append(genre_list[0]["genreNm"] if genre_list else "기타")
            nations.append(nation_list[0]["nationNm"] if nation_list else "기타")
        except requests.exceptions.RequestException:
            genres.append("기타")
            nations.append("기타")

df["장르"] = genres
df["제작국가"] = nations
df["국내외"] = df["제작국가"].apply(lambda x: "국내" if x == "한국" else "해외")

# --- 사이드바 필터 ---
st.sidebar.header("필터")
genre_options = sorted(df["장르"].unique())
selected_genres = st.sidebar.multiselect("장르", genre_options, default=genre_options)

nation_options = ["국내", "해외"]
selected_nations = st.sidebar.multiselect("국내/해외", nation_options, default=nation_options)

filtered = df[df["장르"].isin(selected_genres) & df["국내외"].isin(selected_nations)]

if filtered.empty:
    st.info("필터 조건에 맞는 영화가 없습니다.")
    st.stop()

# 1위 카드는 필터와 무관하게 그날 실제 박스오피스 1위를 보여준다
top = df.sort_values("rank").iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("어제 1위", top["movieNm"])
c2.metric("어제 관객수", f"{top['audiCnt']:,}명")
c3.metric("누적 관객", f"{top['audiAcc']:,}명")

# 표를 한국어 열 이름으로 정리
table = filtered[
    ["rank", "movieNm", "장르", "국내외", "openDt", "audiCnt", "audiAcc", "scrnCnt", "rankInten", "rankOldAndNew"]
].copy()
table.columns = ["순위", "영화명", "장르", "국내외", "개봉일", "관객수", "누적관객", "스크린수", "순위변동", "신규여부"]
table["개봉일"] = table["개봉일"].replace("", "-")
table["신규여부"] = table["신규여부"].map({"NEW": "신규", "OLD": ""})
table = table.sort_values("순위").reset_index(drop=True)

st.subheader("📋 박스오피스 TOP 10")
st.dataframe(table, hide_index=True, use_container_width=True)

st.subheader("📈 관객수 상위 5편")
top5 = table.sort_values("관객수", ascending=False).head(5)
st.bar_chart(top5.set_index("영화명")["관객수"])

# --- 예매 바로가기 ---
# 실시간 상영시간표를 제공하는 공식 오픈API가 없어, 각 예매처 검색 결과 페이지로 연결한다.
st.subheader("🎟️ 예매 바로가기")
st.caption("영화명을 눌러 각 예매처 검색 결과로 이동할 수 있습니다. (시간표·좌석은 이동 후 확인)")

for _, row in table.iterrows():
    movie_nm = row["영화명"]
    q = quote(movie_nm)
    cgv_url = f"https://www.cgv.co.kr/search/?query={q}"
    lotte_url = f"https://www.lottecinema.co.kr/NLCHS/Search?searchText={q}"
    megabox_url = f"https://www.megabox.co.kr/searchIntegration?searchText={q}"

    cols = st.columns([2, 1, 1, 1])
    cols[0].write(f"**{movie_nm}**")
    cols[1].link_button("CGV", cgv_url)
    cols[2].link_button("롯데시네마", lotte_url)
    cols[3].link_button("메가박스", megabox_url)
