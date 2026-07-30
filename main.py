"""여러 화면(main.py, pages/*)에서 공통으로 쓰는 데이터 로딩·가공 함수 모음"""
import re
import requests
import pandas as pd
import streamlit as st

POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"

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


def load_all():
    """지도·제안 화면 모두에서 쓰는 데이터를 한 번에 불러옵니다"""
    raw_df = load_population()
    geojson = load_geojson()
    names = load_names(geojson)
    all_years = compute_by_year(raw_df, names)
    return geojson, names, all_years
