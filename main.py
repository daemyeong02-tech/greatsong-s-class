import time
import pandas as pd
import streamlit as st
import plotly.express as px
from utils.data import load_all, add_stage_column, LABELS, COLORS

st.set_page_config(page_title="전국 고령화 지도", layout="wide")
st.title("🗺️ 전국 고령화 지도")
st.caption("시군구별 65세 이상 인구 비율 (행정안전부 주민등록 인구)")

geojson, names, all_years = load_all()

years = sorted(all_years["연도"].unique().tolist())
latest_idx = len(years) - 1

# ── 세션 상태 기본값 준비 ──
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


def apply_map_click():
    """지도를 클릭했을 때 그 지역을 사이드바 선택값에 반영합니다"""
    click_state = st.session_state.get("map_chart")
    if not click_state:
        return
    points = click_state.get("selection", {}).get("points", [])
    if not points:
        return
    code = points[0].get("location")
    if not code or code == st.session_state.last_clicked_code:
        return
    st.session_state.last_clicked_code = code
    match = names[names["시군구코드"] == code]
    if not match.empty:
        st.session_state.sido_sel = match.iloc[0]["시도"]
        st.session_state.sigungu_sel = match.iloc[0]["시군구"]


apply_map_click()


def reset_filters():
    st.session_state.year_idx = latest_idx
    st.session_state.sido_sel = "전체"
    st.session_state.sigungu_sel = "(선택 안 함)"
    st.session_state.playing = False
    st.session_state.last_clicked_code = None
    st.session_state.pop("map_chart", None)


def toggle_playing():
    st.session_state.playing = not st.session_state.playing


# ── 사이드바 ──
st.sidebar.header("🔎 조건 선택")
st.sidebar.button("🔄 초기화", on_click=reset_filters, width="stretch")

play_label = "⏸ 정지" if st.session_state.playing else "▶ 연도 자동 재생"
st.sidebar.button(play_label, on_click=toggle_playing, width="stretch")

selected_year = st.sidebar.selectbox("① 연도 선택", years, index=st.session_state.year_idx)
if selected_year != years[st.session_state.year_idx]:
    st.session_state.year_idx = years.index(selected_year)

sido_list = ["전체"] + sorted(names["시도"].dropna().unique().tolist())
selected_sido = st.sidebar.selectbox("② 시도 선택", sido_list, key="sido_sel")

merged = all_years[all_years["연도"] == selected_year].copy()

if selected_sido != "전체":
    merged = merged[merged["시도"] == selected_sido]
    view_geojson = {
        "type": "FeatureCollection",
        "features": [f for f in geojson["features"] if f["properties"]["시도"] == selected_sido],
    }
else:
    view_geojson = geojson

sigungu_options = ["(선택 안 함)"] + sorted(merged["시군구"].dropna().unique().tolist())
if st.session_state.sigungu_sel not in sigungu_options:
    st.session_state.sigungu_sel = "(선택 안 함)"
selected_sigungu = st.sidebar.selectbox("③ 시군구 검색", sigungu_options, key="sigungu_sel")

st.sidebar.divider()
st.sidebar.page_link("pages/1_지역_제안하기.py", label="📝 이 지역에 의견 남기기")
st.sidebar.page_link("pages/2_제안_모아보기.py", label="📋 우리 반 제안 모아보기")

merged = add_stage_column(merged)

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
    paper_bgcolor="#eef4fa",
    plot_bgcolor="#eef4fa",
)

st.plotly_chart(
    fig,
    width="stretch",
    on_select="rerun",
    selection_mode="points",
    key="map_chart",
)

# 지도 아래 순위 표 두 개
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

    # 다음 화면(제안하기)에서 이 지역이 자동으로 선택되도록 넘겨줍니다
    st.session_state["proposal_sigungu"] = selected_sigungu
    st.page_link(
        "pages/1_지역_제안하기.py",
        label=f"✏️ {selected_sigungu}에 대한 의견 남기러 가기",
        icon="📝",
    )

# ── 연도 자동 재생 ──
if st.session_state.playing:
    time.sleep(1.2)
    if st.session_state.year_idx < latest_idx:
        st.session_state.year_idx += 1
    else:
        st.session_state.playing = False
    st.rerun()
