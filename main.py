import re
import time
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="전국 고령화 지도", layout="wide")
st.title("🗺️ 전국 고령화 지도")
st.caption("시군구별 65세 이상 인구 비율 (행정안전부 주민등록 인구)")

POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"


@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population():
    # '코드' 열은 앞자리 0이 사라지지 않게 글자로 읽습니다
    return pd.read_csv(POP_URL, dtype={"코드": str})


@st.cache_data(show_spinner="지도 경계를 불러오는 중입니다...")
def load_geojson():
    return requests.get(GEO_URL, timeout=30).json()


raw_df = load_population()
geojson = load_geojson()

# '계_'로 시작하는 나이 열만 (남_·여_ 열까지 더하면 두 배가 됩니다)
total_cols = [c for c in raw_df.columns if c.startswith("계_")]


def age_of(col):
    m = re.match(r"계_(\d+)세", col)
    return int(m.group(1)) if m else None


# 65세 이상 열만 ('계_65세' ~ '계_100세 이상')
elderly_cols = [c for c in total_cols if age_of(c) is not None and age_of(c) >= 65]

# '코드' 앞 5자리 = 시군구 코드
raw_df["시군구코드"] = raw_df["코드"].str[:5]

# 경계 파일에서 코드 → 시군구·시도 이름 짝 만들기
names = pd.DataFrame(
    [
        {
            "시군구코드": str(f["properties"]["코드"]),
            "시군구": f["properties"]["시군구"],
            "시도": f["properties"]["시도"],
        }
        for f in geojson["features"]
    ]
)


@st.cache_data(show_spinner="연도별 고령화율을 계산하는 중입니다...")
def compute_by_year(df, total_cols, elderly_cols, names):
    """연도 × 시군구별로 전체인구·고령인구·고령화율을 한 번에 계산해 둡니다.
    (연도를 바꿀 때마다 다시 계산하지 않도록 미리 전부 만들어 캐시합니다)"""
    df = df.copy()
    df["전체인구"] = df[total_cols].sum(axis=1)
    df["고령인구"] = df[elderly_cols].sum(axis=1)
    grouped = df.groupby(["연도", "시군구코드"])[["전체인구", "고령인구"]].sum().reset_index()
    grouped["고령화율"] = (grouped["고령인구"] / grouped["전체인구"] * 100).round(2)
    grouped = grouped.merge(names, on="시군구코드", how="left")
    return grouped


all_years = compute_by_year(raw_df, total_cols, elderly_cols, names)

years = sorted(all_years["연도"].unique().tolist())
latest_idx = len(years) - 1

# ── 세션 상태 기본값 준비 ──
# year_idx: 연도 선택박스에 key를 쓰지 않고 직접 관리합니다.
#           (자동재생 기능에서 스크립트 중간에 값을 바꿔야 하는데,
#            key가 달린 위젯은 이미 화면에 그려진 뒤에는 값을 바꿀 수 없기 때문입니다)
if "year_idx" not in st.session_state:
    st.session_state.year_idx = latest_idx
if "playing" not in st.session_state:
    st.session_state.playing = False
if "sido_sel" not in st.session_state:
    st.session_state.sido_sel = "전체"
if "sigungu_sel" not in st.session_state:
    st.session_state.sigungu_sel = "(선택 안 함)"
if "last_clicked_code" not in st.session_state:
    st.session_state.last_clicked_code = None


# ── 지도를 클릭했을 때: 이전 실행에서 남은 클릭 정보를 읽어서 반영 ──
# (지도는 화면 아래쪽에서 그려지지만, 그 클릭 결과를 사이드바 선택박스에
#  반영하려면 선택박스를 만들기 '전'인 지금 시점에 처리해야 합니다)
def apply_map_click():
    click_state = st.session_state.get("map_chart")
    if not click_state:
        return
    points = click_state.get("selection", {}).get("points", [])
    if not points:
        return
    code = points[0].get("location")
    if not code or code == st.session_state.last_clicked_code:
        return  # 이미 처리한 클릭이면 무시 (무한 반복 방지)
    st.session_state.last_clicked_code = code
    match = names[names["시군구코드"] == code]
    if not match.empty:
        st.session_state.sido_sel = match.iloc[0]["시도"]
        st.session_state.sigungu_sel = match.iloc[0]["시군구"]


apply_map_click()


# ── 초기화 버튼 콜백 ──
def reset_filters():
    st.session_state.year_idx = latest_idx
    st.session_state.sido_sel = "전체"
    st.session_state.sigungu_sel = "(선택 안 함)"
    st.session_state.playing = False
    st.session_state.last_clicked_code = None
    st.session_state.pop("map_chart", None)


# ── 재생/정지 버튼 콜백 ──
def toggle_playing():
    st.session_state.playing = not st.session_state.playing


# ── 사이드바 ──
st.sidebar.header("🔎 조건 선택")
st.sidebar.button("🔄 초기화", on_click=reset_filters, width="stretch")

play_label = "⏸ 정지" if st.session_state.playing else "▶ 연도 자동 재생"
st.sidebar.button(play_label, on_click=toggle_playing, width="stretch")

selected_year = st.sidebar.selectbox(
    "① 연도 선택", years, index=st.session_state.year_idx
)
# 사용자가 직접 선택박스를 바꾼 경우 year_idx도 같이 맞춰줍니다
if selected_year != years[st.session_state.year_idx]:
    st.session_state.year_idx = years.index(selected_year)

sido_list = ["전체"] + sorted(names["시도"].dropna().unique().tolist())
selected_sido = st.sidebar.selectbox("② 시도 선택", sido_list, key="sido_sel")

# 선택한 연도의 데이터만 꺼내기
merged = all_years[all_years["연도"] == selected_year].copy()

# 시도를 골랐으면 그 시도만 남기고, 지도용 geojson도 그 시도만 남깁니다
if selected_sido != "전체":
    merged = merged[merged["시도"] == selected_sido]
    view_geojson = {
        "type": "FeatureCollection",
        "features": [f for f in geojson["features"] if f["properties"]["시도"] == selected_sido],
    }
else:
    view_geojson = geojson

# 시군구 검색 목록 (시도 필터에 맞춰 자동으로 좁혀집니다)
sigungu_options = ["(선택 안 함)"] + sorted(merged["시군구"].dropna().unique().tolist())
# 이전에 골랐던 시군구가 지금 목록에 없으면(예: 시도를 바꿔서) 안전하게 초기화
if st.session_state.sigungu_sel not in sigungu_options:
    st.session_state.sigungu_sel = "(선택 안 함)"
selected_sigungu = st.sidebar.selectbox("③ 시군구 검색", sigungu_options, key="sigungu_sel")

# 5단계 색 구간 (전국 시군구를 다섯 덩어리로 나눈 실제 경계값)
BINS = [0, 19, 23, 28, 38, 100]
LABELS = ["19% 미만", "19~23%", "23~28%", "28~38%", "38% 이상"]
COLORS = {
    "19% 미만": "#fee6ce",
    "19~23%": "#fdc086",
    "23~28%": "#f79646",
    "28~38%": "#e8590c",
    "38% 이상": "#a63603",
}
merged["단계"] = pd.cut(merged["고령화율"], bins=BINS, labels=LABELS, right=False)

# 단계구분도 그리기 (배경 지도 타일 없이 경계만)
fig = px.choropleth(
    merged,
    geojson=view_geojson,
    locations="시군구코드",
    featureidkey="properties.코드",
    color="단계",
    category_orders={"단계": LABELS},
    color_discrete_map=COLORS,
    hover_name="시군구",
    hover_data={"고령화율": True, "시도": True, "시군구코드": False, "단계": False},
    labels={"고령화율": "65세 이상 비율(%)"},
)
fig.update_geos(fitbounds="locations", visible=False, bgcolor="#eef4fa")
fig.update_layout(
    margin=dict(l=0, r=0, t=10, b=0),
    height=700,
    legend_title_text=f"65세 이상 비율 ({selected_year}년)",
    paper_bgcolor="#eef4fa",  # 지도 바깥 배경색: 페이지와 다르게 줘서 지도 영역이 구분되어 보이도록
    plot_bgcolor="#eef4fa",
)

# on_select="rerun" → 지도를 클릭하면 그 클릭 정보가 담겨 화면이 다시 그려집니다
# (마우스 휠은 기본 동작 그대로 두어서, 지도 위에서는 확대/축소가 됩니다)
st.plotly_chart(
    fig,
    width="stretch",
    on_select="rerun",
    selection_mode="points",
    key="map_chart",
)

# 지도 아래 순위 표 두 개 (순위 번호 포함)
c1, c2 = st.columns(2)
cols = ["시도", "시군구", "고령화율"]

top10 = merged.nlargest(10, "고령화율")[cols].reset_index(drop=True)
top10.index = top10.index + 1
top10.index.name = "순위"

bottom10 = merged.nsmallest(10, "고령화율")[cols].reset_index(drop=True)
bottom10.index = bottom10.index + 1
bottom10.index.name = "순위"

with c1:
    st.subheader("🔴 고령화율 높은 곳 10")
    st.dataframe(top10, width="stretch")
with c2:
    st.subheader("🟢 고령화율 낮은 곳 10")
    st.dataframe(bottom10, width="stretch")

# ── 검색한(또는 지도에서 클릭한) 시군구 상세 정보 ──
if selected_sigungu != "(선택 안 함)":
    st.divider()
    st.subheader(f"📍 {selected_sigungu} 상세 정보")

    row = merged[merged["시군구"] == selected_sigungu].iloc[0]
    code = row["시군구코드"]

    m1, m2, m3 = st.columns(3)
    m1.metric("고령화율", f"{row['고령화율']}%")
    m2.metric("전체 인구", f"{int(row['전체인구']):,}명")
    m3.metric("65세 이상 인구", f"{int(row['고령인구']):,}명")

    # 이 지역의 연도별 고령화율 변화 추이
    trend = all_years[all_years["시군구코드"] == code].sort_values("연도")
    trend_fig = px.line(
        trend,
        x="연도",
        y="고령화율",
        markers=True,
        labels={"연도": "연도", "고령화율": "65세 이상 비율(%)"},
        title=f"{selected_sigungu} 연도별 고령화율 추이 "
        f"({int(trend['연도'].min())}~{int(trend['연도'].max())}년)",
    )
    trend_fig.update_layout(height=350, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(trend_fig, width="stretch")

# ── 연도 자동 재생: 마지막에 처리해서, 현재 화면을 다 보여준 뒤 다음 연도로 넘어갑니다 ──
if st.session_state.playing:
    time.sleep(1.2)
    if st.session_state.year_idx < latest_idx:
        st.session_state.year_idx += 1
    else:
        st.session_state.playing = False  # 마지막 연도까지 갔으면 자동으로 정지
    st.rerun()
