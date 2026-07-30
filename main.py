import re
import os
import time
import datetime
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="전국 고령화 지도", layout="wide")

POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"
SAVE_PATH = "proposals.csv"  # 학급 제안 저장 파일 (Streamlit Cloud는 재시작 시 초기화될 수 있습니다)

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


# ══════════════════════════ 데이터 로딩·가공 함수 ══════════════════════════

@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population():
    # '코드' 열은 앞자리 0이 사라지지 않게 글자로 읽습니다
    return pd.read_csv(POP_URL, dtype={"코드": str})


@st.cache_data(show_spinner="지도 경계를 불러오는 중입니다...")
def load_geojson():
    return requests.get(GEO_URL, timeout=30).json()


def age_of(col):
    m = re.match(r"계_(\d+)세", col)
    return int(m.group(1)) if m else None


@st.cache_data(show_spinner="시군구 이름 목록을 만드는 중입니다...")
def load_names(_geojson):
    """geojson에서 코드 → 시군구·시도 이름 짝을 만듭니다"""
    return pd.DataFrame(
        [
            {
                "시군구코드": str(f["properties"]["코드"]),
                "시군구": f["properties"]["시군구"],
                "시도": f["properties"]["시도"],
            }
            for f in _geojson["features"]
        ]
    )


@st.cache_data(show_spinner="연도별 고령화율을 계산하는 중입니다...")
def compute_by_year(df, names):
    """연도 × 시군구별로 전체인구·고령인구·고령화율을 한 번에 계산해 둡니다.
    (연도를 바꿀 때마다 다시 계산하지 않도록 미리 전부 만들어 캐시합니다)"""
    total_cols = [c for c in df.columns if c.startswith("계_")]
    elderly_cols = [c for c in total_cols if age_of(c) is not None and age_of(c) >= 65]

    df = df.copy()
    df["시군구코드"] = df["코드"].str[:5]
    df["전체인구"] = df[total_cols].sum(axis=1)
    df["고령인구"] = df[elderly_cols].sum(axis=1)

    grouped = df.groupby(["연도", "시군구코드"])[["전체인구", "고령인구"]].sum().reset_index()
    grouped["고령화율"] = (grouped["고령인구"] / grouped["전체인구"] * 100).round(2)
    grouped = grouped.merge(names, on="시군구코드", how="left")
    return grouped


def add_stage_column(df):
    """고령화율 값을 5단계 구간(단계)으로 나눠 새 컬럼을 추가합니다"""
    df = df.copy()
    df["단계"] = pd.cut(df["고령화율"], bins=BINS, labels=LABELS, right=False)
    return df


geojson = load_geojson()
raw_df = load_population()
names = load_names(geojson)
all_years = compute_by_year(raw_df, names)

years = sorted(all_years["연도"].unique().tolist())
latest_idx = len(years) - 1


# ══════════════════════════ 화면 전환용 상태값 ══════════════════════════

if "page" not in st.session_state:
    st.session_state.page = "지도"
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
if "proposal_sigungu" not in st.session_state:
    st.session_state.proposal_sigungu = None


# ══════════════════════════ 사이드바 공통 메뉴 ══════════════════════════

st.sidebar.header("📌 메뉴")
st.session_state.page = st.sidebar.radio(
    "화면 선택",
    ["지도", "지역 제안하기", "제안 모아보기"],
    index=["지도", "지역 제안하기", "제안 모아보기"].index(st.session_state.page),
)
st.sidebar.divider()


# ══════════════════════════ 화면 1: 지도 ══════════════════════════

def render_map_page():
    st.title("🗺️ 전국 고령화 지도")
    st.caption("시군구별 65세 이상 인구 비율 (행정안전부 주민등록 인구)")

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

    st.sidebar.subheader("🔎 조건 선택")
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

    merged = add_stage_column(merged)

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

        def go_to_proposal():
            st.session_state.proposal_sigungu = selected_sigungu
            st.session_state.page = "지역 제안하기"

        st.button(
            f"✏️ {selected_sigungu}에 대한 의견 남기러 가기",
            on_click=go_to_proposal,
        )

    if st.session_state.playing:
        time.sleep(1.2)
        if st.session_state.year_idx < latest_idx:
            st.session_state.year_idx += 1
        else:
            st.session_state.playing = False
        st.rerun()


# ══════════════════════════ 화면 2: 지역 제안하기 ══════════════════════════

def render_proposal_form_page():
    st.title("📝 우리 지역에 의견 남기기")
    st.caption("지도에서 살펴본 지역에 대해, 필요하다고 생각하는 것을 자유롭게 적어 보세요.")

    sido_list = sorted(names["시도"].dropna().unique().tolist())
    prefill_sigungu = st.session_state.proposal_sigungu

    with st.form("proposal_form", clear_on_submit=True):
        작성자 = st.text_input("이름 또는 학번", placeholder="예: 3학년 2반 홍길동")

        col1, col2 = st.columns(2)
        with col1:
            시도 = st.selectbox("시도", sido_list)
        with col2:
            sigungu_options = sorted(names[names["시도"] == 시도]["시군구"].dropna().unique().tolist())
            default_idx = (
                sigungu_options.index(prefill_sigungu)
                if prefill_sigungu in sigungu_options
                else 0
            )
            시군구 = st.selectbox("시군구", sigungu_options, index=default_idx)

        내용 = st.text_area(
            "의견 내용",
            placeholder="예: 이 지역은 고령화율이 높은데 병원이 부족해 보여요. 이동 진료 서비스가 있으면 좋겠습니다.",
            height=150,
        )

        submitted = st.form_submit_button("제출하기", width="stretch")

        if submitted:
            if not 작성자.strip() or not 내용.strip():
                st.warning("이름과 의견 내용을 모두 입력해 주세요.")
            else:
                new_row = pd.DataFrame(
                    [
                        {
                            "제출시각": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "작성자": 작성자.strip(),
                            "시도": 시도,
                            "시군구": 시군구,
                            "의견내용": 내용.strip(),
                        }
                    ]
                )
                if os.path.exists(SAVE_PATH):
                    new_row.to_csv(SAVE_PATH, mode="a", header=False, index=False, encoding="utf-8-sig")
                else:
                    new_row.to_csv(SAVE_PATH, mode="w", header=True, index=False, encoding="utf-8-sig")
                st.session_state.proposal_sigungu = None
                st.success("의견이 등록되었습니다. 감사합니다!")


# ══════════════════════════ 화면 3: 제안 모아보기 ══════════════════════════

def render_proposal_list_page():
    st.title("📋 우리 반 제안 모아보기")

    if not os.path.exists(SAVE_PATH):
        st.info("아직 등록된 의견이 없습니다. '지역 제안하기' 화면에서 먼저 의견을 남겨 주세요.")
        return

    df = pd.read_csv(SAVE_PATH, encoding="utf-8-sig")

    st.metric("지금까지 등록된 의견 수", f"{len(df)}건")

    sido_options = ["전체"] + sorted(df["시도"].dropna().unique().tolist())
    selected_sido = st.selectbox("시도로 걸러보기", sido_options)

    view = df if selected_sido == "전체" else df[df["시도"] == selected_sido]

    st.dataframe(
        view.sort_values("제출시각", ascending=False).reset_index(drop=True),
        width="stretch",
    )

    st.divider()
    st.subheader("📊 시군구별 의견 건수")
    counts = view.groupby(["시도", "시군구"]).size().reset_index(name="건수")
    counts = counts.sort_values("건수", ascending=False).reset_index(drop=True)
    st.dataframe(counts, width="stretch")


# ══════════════════════════ 화면 전환 ══════════════════════════

if st.session_state.page == "지도":
    render_map_page()
elif st.session_state.page == "지역 제안하기":
    render_proposal_form_page()
else:
    render_proposal_list_page()
