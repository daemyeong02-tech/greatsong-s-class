import re
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
latest_year = years[-1]

# ── 사이드바: 연도 선택 · 시도 필터 · 시군구 검색 ──
st.sidebar.header("🔎 조건 선택")

selected_year = st.sidebar.selectbox("① 연도 선택", years, index=len(years) - 1)

sido_list = ["전체"] + sorted(names["시도"].dropna().unique().tolist())
selected_sido = st.sidebar.selectbox("② 시도 선택", sido_list)

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

# 시군구 검색 (박스에 이름을 타이핑하면 목록이 자동으로 좁혀집니다)
sigungu_options = ["(선택 안 함)"] + sorted(merged["시군구"].dropna().unique().tolist())
selected_sigungu = st.sidebar.selectbox("③ 시군구 검색", sigungu_options)

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

st.info("💡 지도 위에서는 마우스 휠을 굴려도 확대되지 않아요. 편하게 스크롤해서 아래 내용을 보세요.")

# config={"scrollZoom": False} → 지도 위에서 마우스 휠을 굴렸을 때
# 지도가 확대되지 않고 페이지가 자연스럽게 스크롤되도록 막아줍니다
st.plotly_chart(fig, width="stretch", config={"scrollZoom": False})

# 지도 아래 순위 표 두 개
c1, c2 = st.columns(2)
cols = ["시도", "시군구", "고령화율"]
with c1:
    st.subheader("🔴 고령화율 높은 곳 10")
    st.dataframe(merged.nlargest(10, "고령화율")[cols].reset_index(drop=True))
with c2:
    st.subheader("🟢 고령화율 낮은 곳 10")
    st.dataframe(merged.nsmallest(10, "고령화율")[cols].reset_index(drop=True))

# ── 검색한 시군구 상세 정보 ──
if selected_sigungu != "(선택 안 함)":
    st.divider()
    st.subheader(f"📍 {selected_sigungu} 상세 정보")

    row = merged[merged["시군구"] == selected_sigungu].iloc[0]
    code = row["시군구코드"]

    m1, m2, m3 = st.columns(3)
    m1.metric("고령화율", f"{row['고령화율']}%")
    m2.metric("전체 인구", f"{int(row['전체인구']):,}명")
    m3.metric("65세 이상 인구", f"{int(row['고령인구']):,}명")

    # 이 지역의 연도별(2015~2026) 고령화율 변화 추이
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
