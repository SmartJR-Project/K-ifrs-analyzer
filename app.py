import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import OpenDartReader
import requests, re, ast
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import logging
logger = logging.getLogger(__name__)
DART_API_KEY = "3ed678c1090649bb93d64ec9e50001dbf01d1f40"

# ─────────────────────────────────────────────────────────────
# 네이버 금융 OHLCV 조회 (pykrx 대체)
# ─────────────────────────────────────────────────────────────
def fetch_naver_ohlcv(ticker, start_dt, end_dt, timeframe="day"):
    """네이버 금융 OHLCV → DataFrame (컬럼: 시가/고가/저가/종가/거래량, 인덱스: 날짜)"""
    try:
        url = (
            f"https://api.finance.naver.com/siseJson.naver?"
            f"symbol={ticker}&requestType=1"
            f"&startTime={start_dt.strftime('%Y%m%d')}"
            f"&endTime={end_dt.strftime('%Y%m%d')}"
            f"&timeframe={timeframe}"
        )
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code != 200:
            return None
        text = resp.text.strip().replace("\n", "").replace("\t", "")
        data = ast.literal_eval(text)
        if not data or len(data) < 2:
            return None
        cols = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=cols)
        # 컬럼명 표준화
        rename_map = {}
        for c in df.columns:
            if "날짜" in str(c): rename_map[c] = "날짜"
            elif "시가" in str(c): rename_map[c] = "시가"
            elif "고가" in str(c): rename_map[c] = "고가"
            elif "저가" in str(c): rename_map[c] = "저가"
            elif "종가" in str(c): rename_map[c] = "종가"
            elif "거래량" in str(c): rename_map[c] = "거래량"
        df = df.rename(columns=rename_map)
        if "날짜" not in df.columns:
            return None
        df["날짜"] = pd.to_datetime(df["날짜"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["날짜"]).set_index("날짜").sort_index()
        for c in ["시가", "고가", "저가", "종가", "거래량"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["종가"])
        return df if len(df) > 0 else None
    except Exception:
        return None

st.set_page_config(page_title="K-IFRS 재무제표 분석기", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .stApp { background-color: #F2F2F2; }
    [data-testid="stSidebar"] { background-color: #2C2C2C !important; }
    [data-testid="stSidebar"] * { color: #FFFFFF !important; }
    [data-testid="stSidebar"] .stMarkdown p, [data-testid="stSidebar"] .stMarkdown li,
    [data-testid="stSidebar"] .stMarkdown span { color: #FFFFFF !important; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: #4DA8DA !important; }
    [data-testid="stSidebar"] label { color: #E0E0E0 !important; }
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] .stTextInput input {
        background-color: #3D3D3D !important; color: #FFFFFF !important; border: 1px solid #555555 !important;
    }
    [data-testid="stSidebar"] .stSelectbox > div > div {
        background-color: #3D3D3D !important; color: #FFFFFF !important; border: 1px solid #555555 !important;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background-color: #0055A4 !important; color: #FFFFFF !important; border: none !important; font-weight: 700 !important;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover { background-color: #003D7A !important; }
    [data-testid="stSidebar"] .stButton > button {
        background-color: #3D3D3D !important; color: #FFFFFF !important; border: 1px solid #555555 !important;
    }
    [data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small { color: #B3B3B3 !important; }
    [data-testid="stSidebar"] hr { border-color: #4A4A4A !important; }
    .stApp h1 { color: #0055A4 !important; }
    .stTabs [data-baseweb="tab-list"] { background-color: #E8E8E8; border-radius: 8px; padding: 4px; }
    .stTabs [data-baseweb="tab"] { color: #2C2C2C !important; font-weight: 600; }
    .stTabs [aria-selected="true"] { background-color: #0055A4 !important; color: #FFFFFF !important; border-radius: 6px; }
    [data-testid="stMetric"] { background-color: #FFFFFF; border: 1px solid #D0D0D0; border-radius: 8px; padding: 12px; }
    [data-testid="stMetric"] label { color: #666666 !important; }
    [data-testid="stMetric"] [data-testid="stMetricValue"] { color: #0055A4 !important; }
</style>
""", unsafe_allow_html=True)

THEME_DB = {
    "🛡️ 방산/우주": {"desc": "방위산업 및 우주항공",
        "tickers": {"012450":"한화에어로스페이스","079550":"LIG넥스원","272210":"한화시스템",
                     "047810":"한국항공우주","064350":"현대로템","299660":"한화오션"}, "etf": "TIGER 방산 (464510)"},
    "🔬 반도체": {"desc": "반도체 설계/제조/장비",
        "tickers": {"005930":"삼성전자","000660":"SK하이닉스","042700":"한미반도체",
                     "058470":"리노공업","403870":"HPSP","357780":"솔브레인","240810":"원익IPS"}, "etf": "KODEX 반도체 (091160)"},
    "🔋 2차전지": {"desc": "배터리, 양극재, 소재",
        "tickers": {"373220":"LG에너지솔루션","006400":"삼성SDI","247540":"에코프로비엠",
                     "086520":"에코프로","003670":"포스코퓨처엠"}, "etf": "TIGER 2차전지 (305540)"},
    "💻 AI/플랫폼": {"desc": "인공지능, 클라우드, 플랫폼",
        "tickers": {"035420":"NAVER","035720":"카카오","259960":"크래프톤","030520":"한글과컴퓨터"}, "etf": "KODEX AI (475710)"},
    "🚗 자동차": {"desc": "완성차, 부품, 자율주행",
        "tickers": {"005380":"현대차","000270":"기아","012330":"현대모비스","204320":"만도","018880":"한온시스템"}, "etf": "KODEX 자동차 (091170)"},
    "💊 바이오": {"desc": "제약, 바이오시밀러, 의료기기",
        "tickers": {"207940":"삼성바이오로직스","068270":"셀트리온","326030":"SK바이오팜","000100":"유한양행","128940":"한미약품"}, "etf": "KODEX 바이오 (244580)"},
    "🚢 조선": {"desc": "조선, 해운, 해양플랜트",
        "tickers": {"329180":"HD현대중공업","042660":"HD한국조선해양","010620":"HD현대미포","299660":"한화오션","010140":"삼성중공업"}, "etf": "TIGER 조선TOP10 (462350)"},
    "🏦 금융": {"desc": "은행, 증권, 보험",
        "tickers": {"105560":"KB금융","055550":"신한지주","086790":"하나금융지주","316140":"우리금융지주","024110":"기업은행"}, "etf": "KODEX 은행 (091170)"},
    "🍜 소비재": {"desc": "식품, 음료, 생활용품",
        "tickers": {"097950":"CJ제일제당","007310":"오뚜기","004370":"농심","051900":"LG생활건강","090430":"아모레퍼시픽"}, "etf": "TIGER 소비재 (228790)"},
}

ACCOUNT_MAP = {
    "매출액":["매출액","수익(매출액)","영업수익","매출","순매출액","영업수익(매출액)","수익","매출수익"],
    "매출원가":["매출원가","영업비용"], "매출총이익":["매출총이익","매출총이익(손실)","매출총손익"],
    "영업이익":["영업이익","영업이익(손실)","영업손익"],
    "당기순이익":["당기순이익","당기순이익(손실)","분기순이익","분기순이익(손실)","반기순이익","반기순이익(손실)",
        "연결당기순이익","연결당기순이익(손실)","연결분기순이익","연결분기순이익(손실)","연결반기순이익","연결반기순이익(손실)",
        "당기순손익","분기순손익","반기순손익"],
    "이자비용":["이자비용","금융비용","금융원가","이자비용(금융비용)"],
    "자산총계":["자산총계"],"부채총계":["부채총계"],"자본총계":["자본총계"],
    "유동자산":["유동자산"],"유동부채":["유동부채"],"비유동부채":["비유동부채"],
    "재고자산":["재고자산"],"현금성자산":["현금및현금성자산","현금 및 현금성자산","현금및현금성자산 등"],
    "매출채권":["매출채권","매출채권및기타유동채권","매출채권 및 기타유동채권","매출채권 및 기타채권","외상매출금","수취채권"],
    "매입채무":["매입채무","매입채무및기타유동채무","매입채무 및 기타유동채무","매입채무 및 기타채무","외상매입금","지급채무"],
}
PERIOD_LABELS = {
    "11011":{"curr":"당기 (연간)","prev":"전기 (전년)","growth":"전년 대비"},
    "11012":{"curr":"당반기 (누적)","prev":"전년 동반기","growth":"전년 동반기 대비"},
    "11013":{"curr":"당1분기","prev":"전년 동1분기","growth":"전년 동분기 대비"},
    "11014":{"curr":"당3분기 (누적)","prev":"전년 동3분기","growth":"전년 동분기 대비"},
}
def to_num(val):
    if val is None or pd.isna(val): return None
    s=str(val).replace(",","").replace(" ","").strip()
    if s in ("","None","nan","-"): return None
    try: return float(s)
    except: return None

def extract_from_df(df):
    result={}; matched={}
    if "fs_div" in df.columns:
        cfs=df[df["fs_div"]=="CFS"]; work=cfs if len(cfs)>0 else df
    else: work=df
    if "account_nm" not in work.columns: return result,matched
    work=work.copy(); work["_acc"]=work["account_nm"].astype(str).str.strip()
    for std,aliases in ACCOUNT_MAP.items():
        for a in aliases:
            m=work[work["_acc"]==a]
            if len(m)>0: result[std]=to_num(m.iloc[0].get("thstrm_amount")); matched[std]=a; break
        if std not in result:
            for a in aliases:
                m=work[work["_acc"].str.contains(a,na=False,regex=False)]
                if len(m)>0: result[std]=to_num(m.iloc[0].get("thstrm_amount")); matched[std]=f"~{m.iloc[0]['_acc']}"; break
    return result,matched

def analyze_debt_asset_structure(df):
    if df is None or len(df)==0: return None
    work=df.copy()
    if "fs_div" in work.columns:
        cfs=work[work["fs_div"]=="CFS"]
        if len(cfs)>0: work=cfs
    if "account_nm" not in work.columns: return None
    work["_acc"]=work["account_nm"].astype(str).str.strip()
    def gv(names,col="thstrm_amount"):
        for nm in names:
            m=work[work["_acc"]==nm]
            if len(m)==0: m=work[work["_acc"].str.contains(nm,na=False,regex=False)]
            if len(m)>0:
                try: return float(str(m.iloc[0][col]).replace(",","").strip())
                except: pass
        return None
    r={}
    fi={"단기차입금":["단기차입금"],"유동성장기부채":["유동성장기부채","유동성장기차입금"],"단기사채":["단기사채"],"장기차입금":["장기차입금"],"사채":["사채"]}
    fc=0;fp=0;fd=[]
    for lb,nms in fi.items():
        vc=gv(nms,"thstrm_amount");vp=gv(nms,"frmtrm_amount")
        if vc is not None: fc+=vc;fd.append({"item":lb,"curr":vc,"prev":vp or 0})
        if vp is not None: fp+=vp
    r["fin_curr"]=fc;r["fin_prev"]=fp;r["fin_detail"]=fd
    r["debt_curr"]=gv(["부채총계"],"thstrm_amount");r["debt_prev"]=gv(["부채총계"],"frmtrm_amount")
    if r["debt_curr"] is not None: r["nfin_curr"]=r["debt_curr"]-fc
    if r["debt_prev"] is not None: r["nfin_prev"]=r["debt_prev"]-fp
    r["asset_curr"]=gv(["자산총계"],"thstrm_amount");r["asset_prev"]=gv(["자산총계"],"frmtrm_amount")
    r["cash_curr"]=gv(["현금및현금성자산","현금및현금등가물"],"thstrm_amount");r["cash_prev"]=gv(["현금및현금성자산","현금및현금등가물"],"frmtrm_amount")
    r["inv_curr"]=gv(["재고자산"],"thstrm_amount");r["inv_prev"]=gv(["재고자산"],"frmtrm_amount")
    r["ca_curr"]=gv(["유동자산"],"thstrm_amount");r["ca_prev"]=gv(["유동자산"],"frmtrm_amount")
    r["recv_curr"]=gv(["매출채권","매출채권및기타유동채권","매출채권 및 기타채권"],"thstrm_amount");r["recv_prev"]=gv(["매출채권","매출채권및기타유동채권","매출채권 및 기타채권"],"frmtrm_amount")
    r["nca_curr"]=gv(["비유동자산"],"thstrm_amount");r["nca_prev"]=gv(["비유동자산"],"frmtrm_amount")
    r["ppe_curr"]=gv(["유형자산"],"thstrm_amount");r["ppe_prev"]=gv(["유형자산"],"frmtrm_amount")
    r["ncfin_curr"]=gv(["비유동금융자산","장기금융상품","기타비유동금융자산"],"thstrm_amount");r["ncfin_prev"]=gv(["비유동금융자산","장기금융상품","기타비유동금융자산"],"frmtrm_amount")
    return r

def extract_accounts(df, report_code="11011"):
    result={"당기":{},"전기":{},"전전기":{},"matched":{},"period_label":PERIOD_LABELS.get(report_code,PERIOD_LABELS["11011"])}
    if "fs_div" in df.columns:
        cfs=df[df["fs_div"]=="CFS"]; work=cfs if len(cfs)>0 else df
    else: work=df
    if "account_nm" not in work.columns: return result
    work=work.copy(); work["_acc"]=work["account_nm"].astype(str).str.strip()
    for std,aliases in ACCOUNT_MAP.items():
        found=False
        for a in aliases:
            m=work[work["_acc"]==a]
            if len(m)>0:
                row=m.iloc[0]; result["당기"][std]=to_num(row.get("thstrm_amount"))
                result["전기"][std]=to_num(row.get("frmtrm_amount")); result["전전기"][std]=to_num(row.get("bfefrmtrm_amount"))
                result["matched"][std]=a; found=True; break
        if not found:
            for a in aliases:
                m=work[work["_acc"].str.contains(a,na=False,regex=False)]
                if len(m)>0:
                    row=m.iloc[0]; result["당기"][std]=to_num(row.get("thstrm_amount"))
                    result["전기"][std]=to_num(row.get("frmtrm_amount")); result["전전기"][std]=to_num(row.get("bfefrmtrm_amount"))
                    result["matched"][std]=f"~{row['_acc']}"; found=True; break
    return result

def supplement_prev_from_api(dart, corp_code, year, report_code, accounts):
    if report_code=="11011": return accounts
    is_items=["매출액","매출원가","매출총이익","영업이익","당기순이익","이자비용"]
    needs=any(accounts["전기"].get(i) is None for i in is_items if accounts["당기"].get(i) is not None)
    if not needs: return accounts
    try:
        prev_df=dart.finstate_all(corp_code, year-1, reprt_code=report_code)
        if prev_df is not None and len(prev_df)>0:
            for col in prev_df.columns:
                try:
                    if str(prev_df[col].dtype)=="string": prev_df[col]=prev_df[col].astype(object)
                except: pass
            prev_vals,_=extract_from_df(prev_df)
            for i in is_items:
                if accounts["전기"].get(i) is None and i in prev_vals: accounts["전기"][i]=prev_vals[i]
            accounts["_prev_supplemented"]=True
    except: accounts["_prev_supplemented"]=False
    return accounts

def fetch_stock_info(ticker):
    price=None; shares=None; trade_date=None; errors=[]
    # ── 1) 네이버 OHLCV로 종가 조회 ─────────────────────────
    try:
        end=datetime.now(); start=end-timedelta(days=15)
        ohlcv = fetch_naver_ohlcv(ticker, start, end)
        if ohlcv is not None and len(ohlcv)>0:
            price=int(ohlcv.iloc[-1]["종가"])
            trade_date=ohlcv.index[-1].strftime("%Y-%m-%d")
    except Exception as e:
        errors.append(f"네이버 OHLCV: {e}")
    # ── 2) Fallback: 네이버 메인 페이지 현재가 ──────────────
    if not price:
        try:
            url=f"https://finance.naver.com/item/main.naver?code={ticker}"
            resp=requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=5)
            if resp.status_code==200:
                soup=BeautifulSoup(resp.text, "html.parser")
                tag=soup.select_one("p.no_today span.blind")
                if tag:
                    price=int(tag.get_text().replace(",",""))
                    trade_date=datetime.now().strftime("%Y-%m-%d")
        except Exception as e:
            errors.append(f"네이버 메인: {e}")
    # ── 3) 상장주식수 ──────────────────────────────────────
    try:
        headers={"User-Agent":"Mozilla/5.0"}
        url=f"https://finance.naver.com/item/main.naver?code={ticker}"
        resp=requests.get(url,headers=headers,timeout=5)
        if resp.status_code==200:
            m=re.search(r'상장주식수.*?([\d,]+)',resp.text,re.DOTALL)
            if m:
                val=m.group(1).replace(",","")
                if val.isdigit() and int(val)>1000: shares=int(val)
            if not shares: errors.append("네이버: 패턴 못찾음")
    except Exception as e: errors.append(f"네이버: {e}")
    if not shares:
        try:
            url2=f"https://m.stock.naver.com/api/stock/{ticker}/integration"
            resp2=requests.get(url2,headers=headers,timeout=5)
            if resp2.status_code==200:
                for pat in [r'"상장주식수[^"]*"[^}]*?"value"\s*:\s*"([\d,]+)"',r'"listedShareCount"\s*:\s*"?([\d,]+)']:
                    m2=re.search(pat,resp2.text)
                    if m2:
                        val=m2.group(1).replace(",","")
                        if val.isdigit() and int(val)>1000: shares=int(val); break
        except Exception as e: errors.append(f"네이버API: {e}")
    return price,shares,trade_date,errors

def fetch_sector_peers(ticker):
    peers = {}; sector_name = ""
    try:
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200: return sector_name, peers


        soup = BeautifulSoup(resp.text, "html.parser")
        upjong_link = None
        for a in soup.select("a[href*='upjong']"):
            href = a.get("href", "")
            if "no=" in href: upjong_link = href; sector_name = a.get_text(strip=True); break
        if not upjong_link:
            section = soup.select_one("div.trade_compare")
            if section:
                a_tag = section.select_one("a[href]")
                if a_tag: upjong_link = a_tag.get("href", ""); sector_name = a_tag.get_text(strip=True)
        if not upjong_link: return sector_name, peers
        upjong_url = f"https://finance.naver.com{upjong_link}" if upjong_link.startswith("/") else upjong_link
        resp2 = requests.get(upjong_url, headers=headers, timeout=5)
        if resp2.status_code == 200:
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            for a in soup2.select("a[href*='/item/main.naver?code=']"):
                href = a.get("href", ""); m = re.search(r"code=(\d{6})", href)
                if m:
                    c = m.group(1); nm = a.get_text(strip=True)
                    if c != ticker and nm and len(nm) > 1 and c not in peers:
                        peers[c] = nm
                        if len(peers) >= 10: break
    except: pass
    return sector_name, peers

# -- 적정주가 3-Way 산출 --
def get_naver_valuation_data(ticker):
    result = {"per": None, "dps": None, "div_yield": None}
    hd = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        from bs4 import BeautifulSoup
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        r = requests.get(url, headers=hd, timeout=5)
        if r.status_code != 200: return result
        soup = BeautifulSoup(r.text, "html.parser")
        for em in soup.select("em#_per"):
            try: result["per"] = float(em.get_text(strip=True).replace(",","")); break
            except: pass
        if not result["per"]:
            m = re.search(r'PER.*?(\d+\.?\d*)\s*배', r.text, re.DOTALL)
            if m:
                try: result["per"] = float(m.group(1))
                except: pass
        tables = soup.select("table")
        for tbl in tables:
            txt = tbl.get_text()
            if "주당배당금" in txt or "배당수익률" in txt:
                for row in tbl.select("tr"):
                    row_txt = " ".join(c.get_text(strip=True) for c in row.select("td, th"))
                    if "주당배당금" in row_txt:
                        nums = re.findall(r'[\d,]+', row_txt.split("주당배당금")[-1])
                        if nums:
                            v = nums[0].replace(",","")
                            if v.isdigit() and int(v) > 0: result["dps"] = int(v)
                    if "배당수익률" in row_txt:
                        nums = re.findall(r'\d+\.?\d*', row_txt.split("배당수익률")[-1])
                        if nums:
                            try: result["div_yield"] = float(nums[0])
                            except: pass
        if not result["dps"] and result["div_yield"]:
            try:
                m2 = re.search(r'현재가.*?(\d[\d,]*)', r.text, re.DOTALL)
                if m2: result["dps"] = int(int(m2.group(1).replace(",","")) * result["div_yield"] / 100)
            except: pass
    except: pass
    return result

def get_peers_per_list(auto_peers, max_peers=8):
    per_list = []
    hd = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if not auto_peers: return per_list
    import time as _t
    for code in list(auto_peers.keys())[:max_peers]:
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            r = requests.get(url, headers=hd, timeout=5)
            if r.status_code == 200:
                m = re.search(r'id="_per"[^>]*>([\d.]+)', r.text)
                if not m: m = re.search(r'PER.*?(\d+\.?\d*)\s*배', r.text, re.DOTALL)
                if m:
                    v = float(m.group(1))
                    if 0 < v < 200: per_list.append({"code": code, "name": auto_peers.get(code, code), "PER": v})
            _t.sleep(0.15)
        except: pass
    return per_list

def calc_three_valuations(ticker, eps, bps, ni_curr, ni_prev, price, shares, auto_peers=None):
    results = {}
    try:
        end_dt = datetime.now(); start_dt = end_dt - timedelta(days=365*5)
        ohlcv = fetch_naver_ohlcv(ticker, start_dt, end_dt, timeframe="month")
        if ohlcv is not None and len(ohlcv) > 10 and bps and bps > 0:
            pbr_s = ohlcv["종가"] / bps; pbr_s = pbr_s[pbr_s > 0]
            if len(pbr_s) > 5:
                q25=pbr_s.quantile(0.25); q50=pbr_s.quantile(0.50); q75=pbr_s.quantile(0.75)
                results["pbr_band"] = {"target": int(bps*q25), "bps": bps, "q25": round(q25,2), "q50": round(q50,2), "q75": round(q75,2), "desc": f"BPS {bps:,.0f}원 x 하단PBR {q25:.2f}배"}
    except: pass
    try:
        if eps and eps > 0 and auto_peers:
            peer_pers = get_peers_per_list(auto_peers)
            if peer_pers:
                vals = [p["PER"] for p in peer_pers]
                avg_p = sum(vals)/len(vals); med_p = sorted(vals)[len(vals)//2]
                results["industry_per"] = {"target": int(eps*med_p), "eps": eps, "avg_per": round(avg_p,1), "med_per": round(med_p,1), "peers": peer_pers, "desc": f"EPS {eps:,.0f}원 x 업종PER {med_p:.1f}배"}
    except: pass
    try:
        nv = get_naver_valuation_data(ticker)
        dps = nv.get("dps")
        if dps and dps > 0:
            g = max(0.01, min(0.12, (ni_curr-ni_prev)/abs(ni_prev))) if ni_curr and ni_prev and ni_prev > 0 else 0.03
            r = 0.085
            if g < r - 0.005:
                results["ddm"] = {"target": int(dps*(1+g)/(r-g)), "dps": dps, "growth_pct": round(g*100,1), "req_return_pct": round(r*100,1), "div_yield": nv.get("div_yield"), "desc": f"DPS {dps:,}원 x (1+{g*100:.1f}%) / ({r*100:.1f}%-{g*100:.1f}%)"}
    except: pass
    return results
# -- 적정주가 3-Way 끝 --


def generate_ai_comment(corp_name, financial_summary, gemini_key):
    """Google Gemini API로 AI 투자 코멘트 생성"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        prompt = f"""당신은 한국 주식시장 전문 재무분석가입니다.
아래 '{corp_name}'의 재무 데이터를 분석하여 투자 의견을 제시해주세요.

{financial_summary}

다음 형식으로 간결하게 답변해주세요 (각 항목 2~3문장):
### 📊 재무 건전성
(부채비율, 유동비율 등 안정성 평가)

### 📈 성장성 & 수익성
(매출/이익 성장률, 영업이익률, ROE 등 평가)

### ⚠️ 리스크 요인
- (주요 리스크 2~3개 bullet)

### 💡 투자 포인트
- (핵심 투자매력 2~3개 bullet)

### 🎯 종합 의견
(3~4문장으로 종합 판단. 면책조항 포함)
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
        }
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            err = resp.json().get("error", {}).get("message", resp.text[:200])
            return f"⚠️ API 오류 ({resp.status_code}): {err}"
    except Exception as e:
        return f"⚠️ 요청 실패: {str(e)}"

def build_financial_summary(accounts, ratios, price=None, shares=None):
    curr = accounts.get("당기", {}); prev = accounts.get("전기", {}); parts = []
    parts.append("【손익】")
    for k in ["매출액","영업이익","당기순이익"]:
        cv = curr.get(k); pv = prev.get(k)
        g = f" (전기대비 {(cv/pv-1)*100:+.1f}%)" if cv and pv and pv != 0 else ""
        parts.append(f"  {k}: {fmt_amt(cv)}{g}")
    parts.append("【재무상태】")
    for k in ["자산총계","부채총계","자본총계"]: parts.append(f"  {k}: {fmt_amt(curr.get(k))}")
    parts.append("【주요 비율】")
    for k in ["영업이익률","순이익률","ROE","ROA","부채비율","유동비율","이자보상배율"]:
        v = ratios.get(k); sf = "배" if k == "이자보상배율" else "%"
        parts.append(f"  {k}: {f'{v:.1f}{sf}' if v is not None else 'N/A'}")
    if price and shares and shares > 0:
        parts.append("【밸류에이션】")
        per = ratios.get("PER"); pbr = ratios.get("PBR")
        parts.append(f"  주가: {price:,}원 / 시총: {fmt_amt(price*shares)}")
        parts.append(f"  PER: {f'{per:.1f}배' if per else 'N/A'} / PBR: {f'{pbr:.1f}배' if pbr else 'N/A'}")
    return "\n".join(parts)

def fetch_multiyear(dart, corp_code, base_year, report_code, years=5):
    all_data = {}
    for yr in range(base_year, base_year - years, -1):
        try:
            df = dart.finstate_all(corp_code, yr, reprt_code=report_code)
            if df is not None and len(df) > 0:
                for col in df.columns:
                    try:
                        if str(df[col].dtype) == "string": df[col] = df[col].astype(object)
                    except: pass
                vals, prev_vals = extract_from_df(df)
                if vals: all_data[yr] = vals
        except: continue
    return all_data

def build_trend_df(multiyear_data):
    rows = []
    for yr in sorted(multiyear_data.keys()):
        d = multiyear_data[yr]
        rev=d.get("매출액"); oi=d.get("영업이익"); ni=d.get("당기순이익")
        ta=d.get("자산총계"); tl=d.get("부채총계"); te=d.get("자본총계"); cl=d.get("유동부채"); ca=d.get("유동자산")
        rows.append({"연도": str(yr), "매출액": rev, "영업이익": oi, "당기순이익": ni,
            "자산총계": ta, "부채총계": tl, "자본총계": te,
            "영업이익률": (oi/rev*100) if rev and oi and rev!=0 else None,
            "순이익률": (ni/rev*100) if rev and ni and rev!=0 else None,
            "ROE": (ni/te*100) if ni and te and te!=0 else None,
            "ROA": (ni/ta*100) if ni and ta and ta!=0 else None,
            "부채비율": (tl/te*100) if tl and te and te!=0 else None,
            "유동비율": (ca/cl*100) if ca and cl and cl!=0 else None})
    return pd.DataFrame(rows)

def make_trend_charts(trend_df):
    charts = {}; yrs = trend_df["연도"].tolist()
    fig1 = go.Figure()
    for col, color, name in [("매출액","#0055A4","매출액"),("영업이익","#4DA8DA","영업이익"),("당기순이익","#7FC8F8","당기순이익")]:
        vals = trend_df[col].tolist()
        fig1.add_trace(go.Bar(x=yrs, y=[v/1e8 if v else 0 for v in vals], name=name, marker_color=color,
            text=[f"{v/1e8:,.0f}" if v else "" for v in vals], textposition="outside", textfont_size=10))
    fig1.update_layout(title="매출액 / 영업이익 / 당기순이익 추이 (억원)", barmode="group", height=400,
        plot_bgcolor="white", paper_bgcolor="#F2F2F2", font=dict(family="Pretendard, sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), yaxis_title="억원")
    charts["revenue"] = fig1
    fig2 = go.Figure()
    for col, color, dash in [("영업이익률","#0055A4","solid"),("순이익률","#4DA8DA","solid"),("ROE","#E8524A","dash"),("ROA","#F4A261","dash")]:
        vals = trend_df[col].tolist()
        fig2.add_trace(go.Scatter(x=yrs, y=vals, name=col, mode="lines+markers+text",
            line=dict(color=color, width=2.5, dash=dash), marker=dict(size=8),
            text=[f"{v:.1f}%" if v else "" for v in vals], textposition="top center", textfont_size=9))
    fig2.update_layout(title="수익성 지표 추이 (%)", height=380, plot_bgcolor="white", paper_bgcolor="#F2F2F2",
        font=dict(family="Pretendard, sans-serif"), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), yaxis_title="%")
    charts["profitability"] = fig2
    fig3 = go.Figure()
    for col, color in [("부채비율","#E8524A"),("유동비율","#0055A4")]:
        vals = trend_df[col].tolist()
        fig3.add_trace(go.Scatter(x=yrs, y=vals, name=col, mode="lines+markers+text",
            line=dict(color=color, width=2.5), marker=dict(size=8),
            text=[f"{v:.0f}%" if v else "" for v in vals], textposition="top center", textfont_size=9))
    fig3.add_hline(y=100, line_dash="dot", line_color="gray", annotation_text="부채비율 100%")
    fig3.add_hline(y=200, line_dash="dot", line_color="lightcoral", annotation_text="유동비율 200%")
    fig3.update_layout(title="안정성 지표 추이 (%)", height=380, plot_bgcolor="white", paper_bgcolor="#F2F2F2",
        font=dict(family="Pretendard, sans-serif"), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), yaxis_title="%")
    charts["stability"] = fig3
    return charts

def calc_ratio(n,d):
    if n is None or d is None or d==0: return None
    return n/d
def calc_growth(c,p):
    if c is None or p is None or p==0: return None
    return (c-p)/abs(p)*100
def calculate_all_ratios(accounts, stock_price=0, shares=0):
    curr=accounts["당기"]; prev=accounts["전기"]; r={}
    r["매출액 증가율"]=calc_growth(curr.get("매출액"),prev.get("매출액"))
    r["영업이익 증가율"]=calc_growth(curr.get("영업이익"),prev.get("영업이익"))
    r["순이익 증가율"]=calc_growth(curr.get("당기순이익"),prev.get("당기순이익"))
    r["총자산 증가율"]=calc_growth(curr.get("자산총계"),prev.get("자산총계"))
    opr=calc_ratio(curr.get("영업이익"),curr.get("매출액")); r["영업이익률"]=opr*100 if opr else None
    npr=calc_ratio(curr.get("당기순이익"),curr.get("매출액")); r["순이익률"]=npr*100 if npr else None
    roe=calc_ratio(curr.get("당기순이익"),curr.get("자본총계")); r["ROE"]=roe*100 if roe else None
    roa=calc_ratio(curr.get("당기순이익"),curr.get("자산총계")); r["ROA"]=roa*100 if roa else None
    dr=calc_ratio(curr.get("부채총계"),curr.get("자본총계")); r["부채비율"]=dr*100 if dr else None
    cr=calc_ratio(curr.get("유동자산"),curr.get("유동부채")); r["유동비율"]=cr*100 if cr else None
    inv=curr.get("재고자산") or 0; ca=curr.get("유동자산"); cl=curr.get("유동부채")
    r["당좌비율"]=(ca-inv)/cl*100 if ca and cl and cl!=0 else None
    r["이자보상배율"]=calc_ratio(curr.get("영업이익"),curr.get("이자비용"))
    if stock_price>0 and shares>0:
        ni=curr.get("당기순이익"); eq=curr.get("자본총계")
        r["EPS"]=ni/shares if ni else None; r["BPS"]=eq/shares if eq else None
        r["PER"]=stock_price/r["EPS"] if r.get("EPS") and r["EPS"]>0 else None
        r["PBR"]=stock_price/r["BPS"] if r.get("BPS") and r["BPS"]>0 else None
        # ── CCC (현금전환주기) ──────────────────────────────────
    cogs    = curr.get("매출원가")
    ar_c    = curr.get("매출채권");  ar_p = prev.get("매출채권")
    inv_c   = curr.get("재고자산");  inv_p = prev.get("재고자산")
    ap_c    = curr.get("매입채무");  ap_p = prev.get("매입채무")
    rev_ccc = curr.get("매출액")

    def _avg(a, b):
        if a is not None and b is not None: return (a + b) / 2
        return a  # 전기 없으면 당기만 사용

    avg_inv = _avg(inv_c, inv_p)
    avg_ar  = _avg(ar_c,  ar_p)
    avg_ap  = _avg(ap_c,  ap_p)

    DIO = (avg_inv / cogs    * 365) if (avg_inv is not None and cogs    not in (None,0)) else None
    DSO = (avg_ar  / rev_ccc * 365) if (avg_ar  is not None and rev_ccc not in (None,0)) else None
    DPO = (avg_ap  / cogs    * 365) if (avg_ap  is not None and cogs    not in (None,0)) else None

    r["DIO"] = round(DIO, 1) if DIO is not None else None
    r["DSO"] = round(DSO, 1) if DSO is not None else None
    r["DPO"] = round(DPO, 1) if DPO is not None else None
    r["CCC"] = round(DIO + DSO - DPO, 1) if (DIO is not None and DSO is not None and DPO is not None) else None
    return r

SIGNAL_RULES={"매출액 증가율":{"good":(10,None),"warn":(0,10),"bad":(None,0)},
    "영업이익 증가율":{"good":(10,None),"warn":(0,10),"bad":(None,0)},
    "순이익 증가율":{"good":(10,None),"warn":(0,10),"bad":(None,0)},
    "총자산 증가율":{"good":(5,None),"warn":(0,5),"bad":(None,0)},
    "영업이익률":{"good":(10,None),"warn":(5,10),"bad":(None,5)},
    "순이익률":{"good":(7,None),"warn":(3,7),"bad":(None,3)},
    "ROE":{"good":(15,None),"warn":(8,15),"bad":(None,8)},
    "ROA":{"good":(5,None),"warn":(2,5),"bad":(None,2)},
    "부채비율":{"good":(None,100),"warn":(100,200),"bad":(200,None)},
    "유동비율":{"good":(200,None),"warn":(100,200),"bad":(None,100)},
    "당좌비율":{"good":(150,None),"warn":(80,150),"bad":(None,80)},
    "이자보상배율":{"good":(3,None),"warn":(1,3),"bad":(None,1)},}
def get_signal(name,value):
    if value is None: return "⬜","N/A"
    rules=SIGNAL_RULES.get(name)
    if not rules: return "⬜","N/A"
    for sig,lbl,(lo,hi) in [("✅","양호",rules["good"]),("⚠️","주의",rules["warn"]),("🔴","위험",rules["bad"])]:
        if (lo is None or value>=lo) and (hi is None or value<hi): return sig,lbl
    return "⬜","N/A"
def fmt_v(v,s="%",d=1): return f"{v:,.{d}f}{s}" if v is not None else "N/A"
def fmt_amt(v):
    if v is None: return "N/A"
    a=v/1e8; return f"{a/1e4:,.1f}조" if abs(a)>=10000 else f"{a:,.0f}억"

for k in ["dart","corp_list","selected_corp","financial_data","api_connected",
           "accounts","ratios","report_code_used","auto_price","auto_shares",
           "price_date","price_errors","multiyear","trend_df"]:
    if k not in st.session_state: st.session_state[k]=None
if "watchlist" not in st.session_state: st.session_state.watchlist=[]
if "openai_key" not in st.session_state: st.session_state.openai_key=""

def connect_dart(api_key):
    try:
        dart=OpenDartReader(api_key); raw=dart.corp_codes
        safe=pd.DataFrame()
        for col in raw.columns: safe[col]=raw[col].astype(str).fillna("")
        safe["stock_code"]=safe["stock_code"].str.strip()
        listed=safe[(safe["stock_code"]!="")&(safe["stock_code"]!="None")&(safe["stock_code"]!="nan")&(safe["stock_code"]!=" ")&(safe["stock_code"].str.len()>=4)].copy()
        return dart,listed[["corp_code","corp_name","stock_code"]].reset_index(drop=True),None
    except Exception as e: return None,None,str(e)
def search_corp(cl,kw):
    if not kw or kw.strip()=="": return pd.DataFrame()
    kw=kw.strip(); return cl[cl["corp_name"].str.contains(kw,case=False,na=False)|cl["stock_code"].str.contains(kw,na=False)].head(20)

def fetch_consensus_target(ticker: str, current_price: int = 0) -> dict:
    """
    컨센서스 목표주가를 여러 소스에서 순차 조회 (Fallback Chain)

    Args:
        ticker: 종목코드 (예: "005930")
        current_price: 현재 주가 (유효성 검증용, 0이면 검증 스킵)

    Returns:
        dict: {
            "target_price": int or None,
            "analyst_count": int or None,
            "rating": str or None,
            "source": str or None,
            "errors": list[str]
        }
    """
    result = {
        "target_price": None,
        "analyst_count": None,
        "rating": None,
        "source": None,
        "errors": []
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    def _is_valid_target(price: int) -> bool:
        """목표주가 유효성 검증 (Sanity Check)"""
        if price is None or price <= 0:
            return False
        # 최소 금액 필터: 한국 주식은 최소 수백~수천원대
        if price < 500:
            return False
        # 현재가 대비 유효 범위 검증 (현재가의 30%~400% 범위)
        if current_price and current_price > 0:
            ratio = price / current_price
            if ratio < 0.3 or ratio > 4.0:
                return False
        return True

    def _parse_price(text: str) -> int:
        """문자열에서 가격 추출 (콤마 제거)"""
        cleaned = text.replace(",", "").replace("원", "").strip()
        try:
            return int(cleaned)
        except ValueError:
            return 0

    # ── Source 1: 네이버 컨센서스 (WiseReport) ──────────────────────
    try:
        url = (
            f"https://navercomp.wisereport.co.kr/v2/company/"
            f"c1070001.aspx?cmp_cd={ticker}"
        )
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 방법 A: 테이블에서 "목표주가" 행 찾기
        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"])
            for i, cell in enumerate(cells):
                if "목표주가" in cell.get_text():
                    # 다음 셀에서 금액 추출
                    for j in range(i + 1, len(cells)):
                        price_text = cells[j].get_text().strip()
                        price_nums = re.findall(r"[\d,]+", price_text)
                        for num_str in price_nums:
                            val = _parse_price(num_str)
                            if _is_valid_target(val):
                                result["target_price"] = val
                                result["source"] = "네이버 WiseReport"
                                break
                    break

        # 방법 B: 텍스트 전체에서 "목표주가 XX,XXX원" 패턴
        if not result["target_price"]:
            text = soup.get_text(separator=" ")
            matches = re.findall(
                r"목표주가\s*[:\s]*([\d,]+)\s*원", text
            )
            for m in matches:
                val = _parse_price(m)
                if _is_valid_target(val):
                    result["target_price"] = val
                    result["source"] = "네이버 WiseReport"
                    break

        # 애널리스트 수 / 투자의견
        text = soup.get_text(separator=" ")
        m_analyst = re.search(r"(\d+)\s*명", text)
        if m_analyst:
            result["analyst_count"] = int(m_analyst.group(1))

        for keyword in ["Strong Buy", "Buy", "매수", "중립", "Neutral", "매도"]:
            if keyword in text:
                result["rating"] = keyword
                break

        if result["target_price"]:
            return result

    except requests.exceptions.Timeout:
        result["errors"].append("WiseReport: 응답 시간 초과")
    except requests.exceptions.RequestException as e:
        result["errors"].append(f"WiseReport: 네트워크 오류")
    except Exception as e:
        result["errors"].append(f"WiseReport: 파싱 오류 ({e})")

    # ── Source 2: FnGuide 컨센서스 ──────────────────────────────────
    try:
        url = (
            f"https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp"
            f"?pGB=1&gicode=A{ticker}"
        )
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 테이블 기반 파싱
        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"])
            for i, cell in enumerate(cells):
                if "목표주가" in cell.get_text():
                    for j in range(i + 1, len(cells)):
                        price_text = cells[j].get_text().strip()
                        price_nums = re.findall(r"[\d,]+", price_text)
                        for num_str in price_nums:
                            val = _parse_price(num_str)
                            if _is_valid_target(val):
                                result["target_price"] = val
                                result["source"] = "FnGuide"
                                break
                    break

        if not result["target_price"]:
            text = soup.get_text(separator=" ")
            matches = re.findall(
                r"목표주가\s*[:\s]*([\d,]+)\s*원?", text
            )
            for m in matches:
                val = _parse_price(m)
                if _is_valid_target(val):
                    result["target_price"] = val
                    result["source"] = "FnGuide"
                    break

        if not result["analyst_count"]:
            m2 = re.search(r"(\d+)\s*명", soup.get_text(separator=" "))
            if m2:
                result["analyst_count"] = int(m2.group(1))

        if result["target_price"]:
            return result

    except requests.exceptions.Timeout:
        result["errors"].append("FnGuide: 응답 시간 초과")
    except requests.exceptions.RequestException as e:
        result["errors"].append(f"FnGuide: 네트워크 오류")
    except Exception as e:
        result["errors"].append(f"FnGuide: 파싱 오류 ({e})")

    # ── Source 3: 네이버 금융 메인 ──────────────────────────────────
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 방법 A: 투자의견 consensus 영역 탐색
        # 네이버 금융의 "투자의견" 영역에서 목표주가 추출
        consensus_area = soup.find("div", {"class": "section_cop_analysis"})
        if not consensus_area:
            consensus_area = soup.find("div", id=re.compile(r"consensus|target|opinion", re.I))
        if not consensus_area:
            consensus_area = soup  # 전체에서 탐색

        # 테이블 행 탐색
        for row in consensus_area.find_all("tr"):
            row_text = row.get_text()
            if "목표주가" in row_text or "목표가" in row_text:
                nums = re.findall(r"[\d,]{4,}", row_text)  # 4자리 이상만
                for num_str in nums:
                    val = _parse_price(num_str)
                    if _is_valid_target(val):
                        result["target_price"] = val
                        result["source"] = "네이버 금융"
                        break
                if result["target_price"]:
                    break

        # 방법 B: 정규식 Fallback (4자리 이상 금액만 허용)
        if not result["target_price"]:
            text = resp.text
            patterns = [
                r"목표주가[^\d]{0,30}([\d,]{4,})",
                r"targetPrice[^\d]{0,20}([\d,]{4,})",
            ]
            for pat in patterns:
                matches = re.findall(pat, text, re.IGNORECASE | re.DOTALL)
                for m in matches:
                    val = _parse_price(m)
                    if _is_valid_target(val):
                        result["target_price"] = val
                        result["source"] = "네이버 금융"
                        break
                if result["target_price"]:
                    break

        # 애널리스트 수
        if not result["analyst_count"]:
            m2 = re.search(r"(\d+)\s*명\s*(?:참여|의견|추정)", resp.text)
            if m2:
                result["analyst_count"] = int(m2.group(1))

        if result["target_price"]:
            return result

    except requests.exceptions.Timeout:
        result["errors"].append("네이버 금융: 응답 시간 초과")
    except requests.exceptions.RequestException as e:
        result["errors"].append(f"네이버 금융: 네트워크 오류")
    except Exception as e:
        result["errors"].append(f"네이버 금융: 파싱 오류 ({e})")

    # 모든 소스 실패
    if not result["errors"]:
        result["errors"].append("모든 소스에서 유효한 목표주가를 찾을 수 없습니다")

    return result



with st.sidebar:
    st.markdown("## 📊 K-IFRS 재무분석기")
    st.markdown("---")
    st.markdown("### 🔑 API 설정")
    api_raw = st.text_input("DART API 키", type="password", value=DART_API_KEY)
    if api_raw:
        ak=api_raw.strip().replace(" ","").replace("\n","").replace("\t","")
        if st.session_state.api_connected==ak:
            st.success(f"✅ 연결됨 ({len(st.session_state.corp_list):,}개)")
        else:
            with st.spinner("🔄 연결 중..."): d,cl,err=connect_dart(ak)
            if d and cl is not None and len(cl)>0:
                st.session_state.dart=d; st.session_state.corp_list=cl; st.session_state.api_connected=ak
                st.success(f"✅ ({len(cl):,}개 상장사)")
            else:
                st.error("❌ 실패")
                if err:
                    with st.expander("에러"): st.code(err)
    else: st.info("👆 API 키 입력")
    with st.expander("🤖 AI 분석 (선택)"):
        if "openai_key" not in st.session_state: st.session_state.openai_key = ""
        if "oai_input" not in st.session_state: st.session_state.oai_input = st.session_state.get("openai_key", "")
        oai_key = st.text_input("Gemini API 키", type="password", placeholder="AIza...", key="oai_input")
        if oai_key: st.session_state.openai_key = oai_key.strip(); st.success("✅ Gemini AI 활성화")
        else: st.caption("입력 시 종합리포트에 AI 코멘트 추가")
    st.markdown("---")
    st.markdown("### 🔍 종목 검색")
    skw=st.text_input("종목명/코드",placeholder="예: 삼성전자")
    if skw and st.session_state.corp_list is not None:
        res=search_corp(st.session_state.corp_list,skw)
        if len(res)>0:
            opts=[f"{r['corp_name']} ({r['stock_code']})" for _,r in res.iterrows()]
            sel=st.selectbox(f"🔎 ({len(res)}건)",opts)
            if sel:
                row=res.iloc[opts.index(sel)]
                st.session_state.selected_corp={"corp_code":row["corp_code"],"corp_name":row["corp_name"],"stock_code":row["stock_code"]}
        else: st.warning("결과 없음")
    st.markdown("---")
    st.markdown("### 📅 조회 조건")
    cy=datetime.now().year; c1,c2=st.columns(2)
    with c1: year=st.selectbox("연도",list(range(cy,cy-6,-1)))
    with c2:
        rmap={"사업보고서":"11011","반기보고서":"11012","1분기보고서":"11013","3분기보고서":"11014"}
        rlabel=st.selectbox("보고서",list(rmap.keys())); rcode=rmap[rlabel]
    trend_years=st.slider("📊 추이 분석 기간",min_value=2,max_value=5,value=5,help="최대 5년치 데이터 수집")
    st.markdown("---")
    st.markdown("### 💰 주가 정보")
    sprice=0; sshares=0
    if st.session_state.selected_corp:
        ticker=st.session_state.selected_corp["stock_code"]; cache_key=f"price_{ticker}"
        if st.session_state.get("_price_cache_key")!=cache_key:
            with st.spinner(f"📡 {ticker} 주가 조회..."): p,s,d,errs=fetch_stock_info(ticker)
            st.session_state.auto_price=p; st.session_state.auto_shares=s; st.session_state.price_date=d; st.session_state.price_errors=errs
            st.session_state["_price_cache_key"]=cache_key
        ap=st.session_state.auto_price; ash=st.session_state.auto_shares; pdt=st.session_state.price_date; perrs=st.session_state.price_errors or []
        if ap and ap>0: st.markdown(f"📅 **{pdt}** 종가"); st.markdown(f"💰 주가: **{ap:,}원**"); sprice=ap
        if ash and ash>0: st.markdown(f"📊 주식수: **{ash:,}주**"); sshares=ash
        if sprice>0 and sshares>0:
            mc=sprice*sshares/1e8; st.markdown(f"💹 시총: **{mc/1e4:,.1f}조**" if mc>=10000 else f"💹 시총: **{mc:,.0f}억**")
        if perrs:
            with st.expander("🔍 조회 로그"):
                for e in perrs: st.caption(e)
        with st.expander("✏️ 수동 수정"):
            mp=st.text_input("주가(원)",value=str(ap) if ap else "",key="mp"); ms=st.text_input("주식수(주)",value=str(ash) if ash else "",key="ms")
            if mp.strip():
                try: sprice=int(mp.replace(",","").strip())
                except: pass
            if ms.strip():
                try: sshares=int(ms.replace(",","").strip())
                except: pass
    else: st.caption("종목 선택 시 자동 조회")
    st.markdown("---")
    can_go=st.session_state.dart is not None and st.session_state.selected_corp is not None
    if st.button("🚀 재무제표 조회 및 분석",type="primary",use_container_width=True,disabled=not can_go):
        corp=st.session_state.selected_corp
        with st.spinner(f"📡 {corp['corp_name']} {year}년 {rlabel}"):
            try:
                df=st.session_state.dart.finstate_all(corp["corp_code"],year,reprt_code=rcode)
                if df is not None and len(df)>0:
                    for col in df.columns:
                        try:
                            if str(df[col].dtype)=="string": df[col]=df[col].astype(object)
                        except: pass
                    st.session_state.financial_data=df; st.session_state.report_code_used=rcode
                    accounts=extract_accounts(df,report_code=rcode)
                    if rcode!="11011": accounts=supplement_prev_from_api(st.session_state.dart,corp["corp_code"],year,rcode,accounts)
                    ratios=calculate_all_ratios(accounts,stock_price=sprice,shares=sshares)
                    st.session_state.accounts=accounts; st.session_state.ratios=ratios
                else: st.error("❌ 데이터 없음"); st.stop()
            except Exception as e: st.error(f"❌ {str(e)}"); st.stop()
        with st.spinner(f"📊 {trend_years}년 추이 데이터 수집 중..."):
            multiyear=fetch_multiyear(st.session_state.dart,corp["corp_code"],year,rcode,years=trend_years)
            if multiyear: st.session_state.multiyear=multiyear; st.session_state.trend_df=build_trend_df(multiyear)
            else: st.session_state.multiyear=None; st.session_state.trend_df=None
        with st.spinner("🏢 동종업계 자동 감지..."):
            sector_name, auto_peers = fetch_sector_peers(corp["stock_code"])
            st.session_state["_auto_sector"] = sector_name; st.session_state["_auto_peers"] = auto_peers
        st.success("✅ 분석 완료!")
    if not can_go: st.caption("API + 종목 선택 후 조회")
    st.markdown("---")
    st.markdown("### ⭐ 관심종목")
    if st.session_state.selected_corp:
        corp=st.session_state.selected_corp; cid=f"{corp['corp_name']} ({corp['stock_code']})"
        if cid not in st.session_state.watchlist:
            if st.button(f"➕ {corp['corp_name']}",use_container_width=True): st.session_state.watchlist.append(cid); st.rerun()
    if st.session_state.watchlist:
        for i,item in enumerate(st.session_state.watchlist):
            c1,c2=st.columns([4,1])
            with c1: st.markdown(f"⭐ {item}")
            with c2:
                if st.button("✕",key=f"d{i}"): st.session_state.watchlist.pop(i); st.rerun()
    else: st.caption("종목 검색 후 추가")

corp=st.session_state.selected_corp
if corp:
    c1,c2=st.columns([3,1])
    with c1: st.markdown(f"# 📊 {corp['corp_name']}"); st.caption(f"{corp['stock_code']} | {year}년 {rlabel}")
    with c2:
        if st.session_state.financial_data is not None: st.metric("항목",f"{len(st.session_state.financial_data):,}개")
else: st.markdown("# 📊 K-IFRS 재무제표 분석기"); st.markdown("##### 사이드바에서 종목 검색 → 조회")

tab1,tab2,tab3,tab4,tab5,tab6,tab7=st.tabs(["📈 재무분석","📉 주가추이","🎯 목표주가","🔄 매매동향","🏢 동종업계","📰 공시/뉴스","📋 종합리포트"])

with tab1:
    if st.session_state.ratios is not None and st.session_state.accounts is not None:
        ratios=st.session_state.ratios; accounts=st.session_state.accounts; curr=accounts["당기"]; prev=accounts["전기"]
        pl=accounts.get("period_label",PERIOD_LABELS["11011"]); rc=st.session_state.report_code_used or "11011"
        if rc!="11011":
            supp="✅ 전년동기 보완" if accounts.get("_prev_supplemented") else ""
            st.info(f"📅 **{rlabel}** | 비교: **{pl['growth']}** | {supp}")
        st.markdown("### 💰 주요 재무 현황")
        m1,m2,m3,m4=st.columns(4)
        for col,nm in [(m1,"매출액"),(m2,"영업이익"),(m3,"당기순이익"),(m4,"자산총계")]:
            with col: v=curr.get(nm); d=calc_growth(v,prev.get(nm)); st.metric(nm,fmt_amt(v),f"{d:+.1f}% ({pl['growth']})" if d is not None else None)
        st.markdown("---")
        cat1,cat2=st.columns(2)
        with cat1:
            st.markdown(f"### 📈 성장성 ({pl['growth']})")
            for nm in ["매출액 증가율","영업이익 증가율","순이익 증가율","총자산 증가율"]:
                v=ratios.get(nm); sig,_=get_signal(nm,v); _c="#2E7D32" if sig=="✅" else "#FF8F00" if sig=="⚠️" else "#E8524A" if sig=="🔴" else "#999"; st.markdown(f"{sig} **{nm}** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_c}'>{fmt_v(v)}</span>", unsafe_allow_html=True)
        with cat2:
            st.markdown("### 💎 수익성")
            if rc!="11011": st.caption(f"※ {pl['curr']} 누적")
            for nm in ["영업이익률","순이익률","ROE","ROA"]:
                v=ratios.get(nm); sig,_=get_signal(nm,v); _c="#2E7D32" if sig=="✅" else "#FF8F00" if sig=="⚠️" else "#E8524A" if sig=="🔴" else "#999"; st.markdown(f"{sig} **{nm}** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_c}'>{fmt_v(v)}</span>", unsafe_allow_html=True)
        cat3,cat4=st.columns(2)
        with cat3:
            st.markdown("### 🛡️ 안정성")
            for nm in ["부채비율","유동비율","당좌비율","이자보상배율"]:
                v=ratios.get(nm); sig,_=get_signal(nm,v); sf="배" if nm=="이자보상배율" else "%"
                _c="#2E7D32" if sig=="✅" else "#FF8F00" if sig=="⚠️" else "#E8524A" if sig=="🔴" else "#999"; st.markdown(f"{sig} **{nm}** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_c}'>{fmt_v(v,sf)}</span>", unsafe_allow_html=True)
        with cat4:
            st.markdown("### 🏷️ 가치평가")
            if ratios.get("PER") is not None or ratios.get("PBR") is not None:
                if rc!="11011": st.caption("⚠️ 분기/반기 EPS는 누적치")
                for nm,sf in [("EPS","원"),("BPS","원"),("PER","배"),("PBR","배")]:
                    v=ratios.get(nm)
                    if v is not None:
                        vt = f"{v:,.0f}{sf}" if sf=="원" else f"{v:,.2f}{sf}"
                        sig2 = ""
                        if nm=="PER": sig2 = " ✅" if v<15 else (" ⚠️" if v<25 else " 🔴")
                        elif nm=="PBR": sig2 = " ✅" if v<1.5 else (" ⚠️" if v<3 else " 🔴")
                        _c2="#2E7D32" if "✅" in sig2 else "#FF8F00" if "⚠️" in sig2 else "#E8524A" if "🔴" in sig2 else "#0055A4"; st.markdown(f"**{nm}** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_c2}'>{vt}</span>{sig2}", unsafe_allow_html=True)
                    else: st.markdown(f"**{nm}** &nbsp; <span style='font-size:1.6em;font-weight:800;color:#999'>N/A</span>", unsafe_allow_html=True)
            else: st.info("💡 주가 자동입력 후 **[🚀 조회]**를 다시 눌러주세요.")
        st.markdown("---")
        st.markdown("### 🔄 운전자본 효율성 (CCC)")

        DIO_v = ratios.get("DIO"); DSO_v = ratios.get("DSO")
        DPO_v = ratios.get("DPO"); CCC_v = ratios.get("CCC")

        c1,c2,c3,c4 = st.columns(4)
        def _day_metric(col,label,val,help_txt):
            col.metric(label, f"{val:,.1f}일" if val is not None else "N/A", help=help_txt)
        _day_metric(c1,"📦 DIO (재고회전일수)",  DIO_v, "평균 재고자산 / 매출원가 × 365\n낮을수록 재고 효율 ↑")
        _day_metric(c2,"📬 DSO (매출채권회전일수)",DSO_v,"평균 매출채권 / 매출액 × 365\n낮을수록 현금회수 빠름")
        _day_metric(c3,"🧾 DPO (매입채무회전일수)",DPO_v,"평균 매입채무 / 매출원가 × 365\n높을수록 지급유예 유리")
        _day_metric(c4,"💵 CCC (현금전환주기)",   CCC_v, "DIO + DSO − DPO\n음수면 현금을 미리 받는 구조")

        if CCC_v is not None:
            if   CCC_v <   0: sig=("🟢 음수 CCC",  "#1a7a4a","현금을 미리 받고 나중에 지급 — 매우 우수")
            elif CCC_v <=  30: sig=("🟢 매우 짧음","#1a7a4a","현금 순환 속도 우수")
            elif CCC_v <=  60: sig=("🟡 양호",      "#b8860b","업종 평균 수준")
            elif CCC_v <= 120: sig=("🟠 주의",      "#c05000","운전자본 부담 증가 가능")
            else:              sig=("🔴 위험",      "#a00000","현금 묶임 심각 — 세부 점검 필요")
            lb,cl,desc=sig
            st.markdown(
                f"<div style='background:{cl}18;border-left:4px solid {cl};border-radius:6px;"
                f"padding:10px 16px;margin-top:8px'>"
                f"<span style='color:{cl};font-weight:700;font-size:1.05em'>{lb}</span>"
                f"&nbsp;&nbsp;<span style='color:#444'>{desc}</span>"
                f"&nbsp;&nbsp;<span style='color:{cl};font-weight:700'>CCC = {CCC_v:+.1f}일</span></div>",
                unsafe_allow_html=True)

        if any(v is not None for v in [DIO_v,DSO_v,DPO_v]):
            import plotly.graph_objects as go
            fig_ccc=go.Figure()
            for nm,val,clr in [("📦 DIO",DIO_v,"#4C9BE8"),("📬 DSO",DSO_v,"#F4A261"),("🧾 DPO",DPO_v,"#2EC4B6")]:
                if val is not None:
                    fig_ccc.add_trace(go.Bar(name=nm,x=[val],y=["구성요소"],orientation="h",
                        marker_color=clr,text=f"{val:.1f}일",textposition="inside",width=0.4))
            fig_ccc.update_layout(barmode="stack",height=120,
                margin=dict(l=10,r=10,t=10,b=10),legend=dict(orientation="h",y=-0.4),
                xaxis_title="일수",plot_bgcolor="rgba(0,0,0,0)",paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_ccc,use_container_width=True)
            st.caption("💡 DIO(재고)+DSO(채권) = 자금 묶임 | DPO(채무) = 지급유예 | CCC = 순 현금 묶임 기간")

        if st.session_state.financial_data is not None:
            _str=analyze_debt_asset_structure(st.session_state.financial_data)
            if _str and _str.get("debt_curr"):
                st.markdown("---")
                st.markdown("### 🏗️ 자산/부채 구조 분석")
                _s1,_s2=st.columns(2)
                with _s1:
                    st.markdown("#### 💳 부채 구조")
                    dt=_str["debt_curr"];dp=_str.get("debt_prev")
                    fc=_str.get("fin_curr",0);fp=_str.get("fin_prev",0)
                    nfc=_str.get("nfin_curr");nfp=_str.get("nfin_prev")
                    st.markdown(f"**부채총계** &nbsp; <span style='font-size:1.6em;font-weight:800'>{fmt_amt(dt)}</span>",unsafe_allow_html=True)
                    fr=fc/dt*100 if dt else 0
                    fc_chg=((fc-fp)/fp*100) if fp else None
                    _fcc="#E8524A" if fc_chg and fc_chg>5 else "#2E7D32" if fc_chg and fc_chg<-5 else "#FF8F00" if fc_chg else "#999"
                    st.markdown(f"**금융부채** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_fcc}'>{fmt_amt(fc)}</span> &nbsp; (비중 {fr:.1f}%)"+(f" &nbsp; <span style='color:{_fcc}'>{fc_chg:+.1f}%</span>" if fc_chg is not None else ""),unsafe_allow_html=True)
                    if nfc is not None:
                        nfr=nfc/dt*100 if dt else 0
                        nfc_chg=((nfc-nfp)/nfp*100) if nfp else None
                        _ncc="#E8524A" if nfc_chg and nfc_chg>5 else "#2E7D32" if nfc_chg and nfc_chg<-5 else "#FF8F00" if nfc_chg else "#999"
                        st.markdown(f"**비금융부채** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_ncc}'>{fmt_amt(nfc)}</span> &nbsp; (비중 {nfr:.1f}%)"+(f" &nbsp; <span style='color:{_ncc}'>{nfc_chg:+.1f}%</span>" if nfc_chg is not None else ""),unsafe_allow_html=True)
                    if _str["fin_detail"]:
                        with st.expander("📋 금융부채 상세"):
                            for _fd in _str["fin_detail"]:
                                _fdchg=(((_fd["curr"]-_fd["prev"])/_fd["prev"])*100) if _fd["prev"] else None
                                _fdc="#E8524A" if _fdchg and _fdchg>0 else "#2E7D32" if _fdchg and _fdchg<0 else "#999"
                                st.markdown(f"• **{_fd['item']}** &nbsp; <span style='font-weight:700;color:{_fdc}'>{fmt_amt(_fd['curr'])}</span>"+(f" &nbsp; ({_fdchg:+.1f}%)" if _fdchg is not None else ""),unsafe_allow_html=True)
                with _s2:
                    st.markdown("#### 🏦 자산 구성")
                    at=_str.get("asset_curr");ap=_str.get("asset_prev")
                    cc=_str.get("cash_curr");cp=_str.get("cash_prev")
                    ic=_str.get("inv_curr");ip=_str.get("inv_prev")
                    if at:
                        st.markdown(f"**자산총계** &nbsp; <span style='font-size:1.6em;font-weight:800'>{fmt_amt(at)}</span>",unsafe_allow_html=True)
                        if cc is not None:
                            cr=cc/at*100;crp=(cp/ap*100) if cp and ap else None
                            _ccc="#2E7D32" if crp and cr>crp else "#E8524A" if crp and cr<crp else "#0055A4"
                            st.markdown(f"**현금성자산** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_ccc}'>{fmt_amt(cc)}</span> &nbsp; (비중 <b>{cr:.1f}%</b>)"+(f" &nbsp; 전기 {crp:.1f}%" if crp else ""),unsafe_allow_html=True)
                        if ic is not None:
                            ir=ic/at*100;irp=(ip/ap*100) if ip and ap else None
                            _icc="#E8524A" if irp and ir>irp+2 else "#2E7D32" if irp and ir<irp-2 else "#0055A4"
                            st.markdown(f"**재고자산** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_icc}'>{fmt_amt(ic)}</span> &nbsp; (비중 <b>{ir:.1f}%</b>)"+(f" &nbsp; 전기 {irp:.1f}%" if irp else ""),unsafe_allow_html=True)
                        if cc is not None or ic is not None:
                            tot=(cc or 0)+(ic or 0);tr=tot/at*100
                            tp=((cp or 0)+(ip or 0));trp=(tp/ap*100) if ap else None
                            _tcc="#0055A4"
                            st.markdown(f"**현금+재고** &nbsp; <span style='font-size:1.6em;font-weight:800;color:{_tcc}'>{fmt_amt(tot)}</span> &nbsp; (비중 <b>{tr:.1f}%</b>)"+(f" &nbsp; 전기 {trp:.1f}%" if trp else ""),unsafe_allow_html=True)
        st.markdown("---"); st.markdown("### 📊 종합 시그널")
        good=warn=bad=0
        for nm in SIGNAL_RULES:
            v=ratios.get(nm); sig,_=get_signal(nm,v)
            if sig=="✅": good+=1
            elif sig=="⚠️": warn+=1
            elif sig=="🔴": bad+=1
        total=good+warn+bad
        if total>0:
            score=int((good*100+warn*50)/total); s1,s2,s3,s4=st.columns(4)
            s1.metric("종합",f"{score}점"); s2.metric("✅",f"{good}개"); s3.metric("⚠️",f"{warn}개"); s4.metric("🔴",f"{bad}개")
            if score>=75: st.success("📊 **양호**")
            elif score>=50: st.warning("📊 **보통**")
            else: st.error("📊 **주의**")
        if st.session_state.trend_df is not None and len(st.session_state.trend_df) >= 2:
            st.markdown("---"); st.markdown(f"### 📊 {len(st.session_state.trend_df)}개년 추이 분석")
            charts = make_trend_charts(st.session_state.trend_df); st.plotly_chart(charts["revenue"], use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
            ch1, ch2 = st.columns(2)
            with ch1: st.plotly_chart(charts["profitability"], use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
            with ch2: st.plotly_chart(charts["stability"], use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
            with st.expander("📋 추이 데이터 상세"):
                tdf = st.session_state.trend_df.copy()
                for c in ["매출액","영업이익","당기순이익","자산총계","부채총계","자본총계"]:
                    if c in tdf.columns: tdf[c] = tdf[c].apply(lambda x: fmt_amt(x) if x else "N/A")
                for c in ["영업이익률","순이익률","ROE","ROA","부채비율","유동비율"]:
                    if c in tdf.columns: tdf[c] = tdf[c].apply(lambda x: f"{x:.1f}%" if x else "N/A")
                st.dataframe(tdf, use_container_width=True, hide_index=True)
        with st.expander("🔍 계정 매칭"):
            matched=accounts.get("matched",{}); rows=[{"계정":nm,"매칭":matched.get(nm,"❌"),"당기":fmt_amt(curr.get(nm)),"전기":fmt_amt(prev.get(nm))} for nm in ACCOUNT_MAP]
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
        with st.expander("📄 원시 데이터"):
            df=st.session_state.financial_data; dc=[c for c in ["fs_nm","sj_nm","account_nm","thstrm_amount","frmtrm_amount"] if c in df.columns]
            st.dataframe(df[dc],use_container_width=True,height=400)
    elif st.session_state.financial_data is not None: st.warning("⚠️ 추출 실패"); st.dataframe(st.session_state.financial_data,use_container_width=True)
    else: st.markdown("### 📈 재무분석\n\n종목 선택 → **[🚀 조회]**")

with tab2:
    st.markdown("### 📉 주가 추이")
    if st.session_state.selected_corp:
        ticker = st.session_state.selected_corp["stock_code"]
        sel_period = st.selectbox("📅 조회 기간", ["1개월","3개월","6개월","1년","3년","5년"], index=3, key="price_period")
        period_map = {"1개월":30, "3개월":90, "6개월":180, "1년":365, "3년":1095, "5년":1825}
        days = period_map[sel_period]; end_dt = datetime.now(); start_dt = end_dt - timedelta(days=days)
        cache_key_price = f"ohlcv3_{ticker}_{days}"
        if st.session_state.get("_ohlcv_cache_key") != cache_key_price:
            with st.spinner("📡 주가 + 시장지수 조회 중..."):
                try:
                    ohlcv = fetch_naver_ohlcv(ticker, start_dt, end_dt)
                    st.session_state["_ohlcv_data"] = ohlcv
                except Exception as e:
                    st.error(f"❌ 주가 조회 실패: {e}"); st.session_state["_ohlcv_data"] = None
                # ── 시장지수 부분은 기존 그대로 유지 ──
                market_name = ""; market_index = None; mkt_err = ""
                try:
                    import xml.etree.ElementTree as ET
                    detect_url = f"https://finance.naver.com/item/main.naver?code={ticker}"
                    detect_resp = requests.get(detect_url, headers={"User-Agent":"Mozilla/5.0"}, timeout=5)
                    if detect_resp.status_code == 200:
                        if "코스닥" in detect_resp.text[:5000]: market_name = "코스닥"; idx_symbol = "KOSDAQ"
                        else: market_name = "코스피"; idx_symbol = "KOSPI"
                        idx_url = f"https://fchart.stock.naver.com/sise.nhn?symbol={idx_symbol}&timeframe=day&count={days+30}&requestType=0"
                        idx_resp = requests.get(idx_url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
                        if idx_resp.status_code == 200:
                            root = ET.fromstring(idx_resp.text); idx_rows = []
                            for item in root.iter("item"):
                                vals = item.get("data", "").split("|")
                                if len(vals) >= 5:
                                    try: idx_rows.append({"날짜": pd.to_datetime(vals[0]), "종가": float(vals[4])})
                                    except: pass
                            if idx_rows: market_index = pd.DataFrame(idx_rows).set_index("날짜").sort_index()
                        else: mkt_err = f"지수API HTTP {idx_resp.status_code}"
                    else: mkt_err = f"네이버 HTTP {detect_resp.status_code}"
                    if market_index is None or (market_index is not None and len(market_index) == 0):
                        if not mkt_err: mkt_err = "지수 데이터 파싱 실패"; market_index = None
                except Exception as e: mkt_err = str(e)
                st.session_state["_market_name"] = market_name; st.session_state["_market_index"] = market_index
                st.session_state["_market_err"] = mkt_err; st.session_state["_ohlcv_cache_key"] = cache_key_price
        ohlcv = st.session_state.get("_ohlcv_data"); market_name = st.session_state.get("_market_name", ""); market_index = st.session_state.get("_market_index")
        if ohlcv is not None and len(ohlcv) > 0:
            if market_name:
                badge_color = "#0055A4" if market_name == "코스피" else "#E8524A"
                st.markdown(f"<span style='background:{badge_color};color:white;padding:4px 12px;border-radius:12px;font-size:13px;font-weight:600;'>📊 {market_name} 상장</span>", unsafe_allow_html=True)
            for ma in [5, 20, 60, 120]:
                if len(ohlcv) >= ma: ohlcv[f"MA{ma}"] = ohlcv["종가"].rolling(window=ma).mean()
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
            fig.add_trace(go.Candlestick(x=ohlcv.index, open=ohlcv["시가"], high=ohlcv["고가"], low=ohlcv["저가"], close=ohlcv["종가"], name="주가",
                increasing_line_color="#E8524A", decreasing_line_color="#0055A4", increasing_fillcolor="#E8524A", decreasing_fillcolor="#0055A4"), row=1, col=1)
            for ma_col, color in {"MA5":"#FF9800","MA20":"#E8524A","MA60":"#4DA8DA","MA120":"#9C27B0"}.items():
                if ma_col in ohlcv.columns: fig.add_trace(go.Scatter(x=ohlcv.index, y=ohlcv[ma_col], name=ma_col, line=dict(color=color, width=1), opacity=0.7), row=1, col=1)
            vol_colors = ["#E8524A" if c >= o else "#0055A4" for c, o in zip(ohlcv["종가"], ohlcv["시가"])]
            fig.add_trace(go.Bar(x=ohlcv.index, y=ohlcv["거래량"], name="거래량", marker_color=vol_colors, opacity=0.5), row=2, col=1)
            fig.update_layout(height=600, showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                plot_bgcolor="white", paper_bgcolor="#F2F2F2", xaxis_rangeslider_visible=False, font=dict(family="Pretendard, sans-serif"))
            fig.update_xaxes(showgrid=True, gridcolor="#E0E0E0"); fig.update_yaxes(showgrid=True, gridcolor="#E0E0E0")
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
            last=ohlcv.iloc[-1]; first=ohlcv.iloc[0]; chg=(last["종가"]-first["종가"])/first["종가"]*100
            mc1,mc2,mc3,mc4,mc5 = st.columns(5)
            mc1.metric("현재가", f"{int(last['종가']):,}원"); mc2.metric(f"{sel_period} 수익률", f"{chg:+.1f}%")
            mc3.metric("최고가", f"{int(ohlcv['고가'].max()):,}원"); mc4.metric("최저가", f"{int(ohlcv['저가'].min()):,}원")
            mc5.metric("평균거래량", f"{int(ohlcv['거래량'].mean()):,}")
            st.markdown("---")
            if market_index is not None and len(market_index) > 0 and market_name:
                st.markdown(f"### 📊 {market_name} 지수 대비 상대 성과")
                stock_norm = (ohlcv["종가"] / ohlcv["종가"].iloc[0] - 1) * 100; idx_close = market_index["종가"]
                index_norm = (idx_close / idx_close.iloc[0] - 1) * 100; common_dates = stock_norm.index.intersection(index_norm.index)
                if len(common_dates) > 5:
                    relative = stock_norm.loc[common_dates] - index_norm.loc[common_dates]
                    fig_rel = go.Figure()
                    fig_rel.add_trace(go.Scatter(x=common_dates, y=stock_norm.loc[common_dates], name=st.session_state.selected_corp["corp_name"],
                        line=dict(color="#0055A4", width=2.5), fill="tozeroy", fillcolor="rgba(0,85,164,0.08)"))
                    fig_rel.add_trace(go.Scatter(x=common_dates, y=index_norm.loc[common_dates], name=f"{market_name} 지수", line=dict(color="#E8524A", width=2, dash="dash")))
                    fig_rel.add_trace(go.Scatter(x=common_dates, y=relative, name="상대수익률 (α)", line=dict(color="#2E7D32", width=1.5, dash="dot"), opacity=0.7))
                    fig_rel.add_hline(y=0, line_dash="solid", line_color="gray", line_width=0.5)
                    fig_rel.update_layout(height=420, plot_bgcolor="white", paper_bgcolor="#F2F2F2", yaxis_title="수익률 (%)", font=dict(family="Pretendard, sans-serif"),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5), hovermode="x unified")
                    st.plotly_chart(fig_rel, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
                    stock_ret = stock_norm.loc[common_dates].iloc[-1]; index_ret = index_norm.loc[common_dates].iloc[-1]; rel_ret = stock_ret - index_ret
                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric(f"📈 {st.session_state.selected_corp['corp_name']}", f"{stock_ret:+.1f}%")
                    rc2.metric(f"📊 {market_name} 지수", f"{index_ret:+.1f}%")
                    rc3.metric("🏆 상대수익률", f"{rel_ret:+.1f}%p", delta="시장 대비 초과 ✅" if rel_ret > 0 else "시장 대비 부진 ⚠️", delta_color="normal" if rel_ret > 0 else "inverse")
                    if rel_ret > 10: st.success(f"🏆 **크게 아웃퍼폼** — {sel_period}간 {market_name} 대비 **{rel_ret:+.1f}%p** 초과 수익")
                    elif rel_ret > 0: st.info(f"📈 **소폭 아웃퍼폼** — {sel_period}간 {market_name} 대비 **{rel_ret:+.1f}%p**")
                    elif rel_ret > -10: st.warning(f"📉 **소폭 언더퍼폼** — {sel_period}간 {market_name} 대비 **{rel_ret:+.1f}%p**")
                    else: st.error(f"📉 **크게 언더퍼폼** — {sel_period}간 {market_name} 대비 **{rel_ret:+.1f}%p**")
                else: st.warning(f"⚠️ 겹치는 거래일 부족 ({len(common_dates)}일)")
            else:
                mkt_err = st.session_state.get("_market_err", "")
                if mkt_err: st.caption(f"⚠️ 시장 지수 비교 불가: {mkt_err}")
                else: st.caption("⚠️ 시장 지수 데이터를 불러오지 못했습니다.")
        else: st.warning("주가 데이터가 없습니다.")
    else: st.info("👈 사이드바에서 종목을 선택해주세요.")

with tab3:
    st.markdown("### 🎯 목표주가 & 적정가 분석")

    if st.session_state.selected_corp and st.session_state.accounts:
        ticker = st.session_state.selected_corp["stock_code"]
        corp_name = st.session_state.selected_corp["corp_name"]
        curr = st.session_state.accounts["당기"]
        current_price = st.session_state.auto_price or 0
        total_shares = st.session_state.auto_shares or 0

        # ── 1. 컨센서스 목표주가 조회 ───────────────────────────────
        with st.spinner("📡 컨센서스 목표주가 조회 중..."):
            consensus = fetch_consensus_target(ticker, current_price)

        target_price = consensus["target_price"]
        analyst_count = consensus["analyst_count"]
        consensus_source = consensus["source"]
        consensus_errors = consensus["errors"]

        # ── 2. PER / PBR 기반 적정가 계산 ───────────────────────────
        ni = curr.get("당기순이익")
        eq = curr.get("자본총계")
        fair_per = None
        fair_pbr = None
        eps = None
        bps = None

        if ni and total_shares and total_shares > 0:
            eps = ni / total_shares
            if eps > 0:
                fair_per = {
                    per: int(eps * per) for per in [10, 12, 15, 20]
                }

        if eq and total_shares and total_shares > 0:
            bps = eq / total_shares
            if bps > 0:
                fair_pbr = {
                    pbr: int(bps * pbr) for pbr in [0.5, 0.8, 1.0, 1.5, 2.0]
                }

        # ── 3. UI 렌더링 ────────────────────────────────────────────
        st.markdown("#### 📊 현재 주가 vs 적정가")

        if current_price > 0:
            col1, col2 = st.columns(2)

            # ── 3-1. 컨센서스 목표주가 (좌측) ────────────────────────
            with col1:
                st.markdown("##### 🏷️ 컨센서스 목표주가")

                if target_price:
                    upside = (target_price - current_price) / current_price * 100

                    st.metric(
                        "목표주가",
                        f"{target_price:,}원",
                        f"{upside:+.1f}% 괴리율"
                    )

                    # 부가 정보
                    info_parts = []
                    if analyst_count:
                        info_parts.append(f"📊 애널리스트 {analyst_count}명 참여")
                    if consensus.get("rating"):
                        info_parts.append(f"💡 투자의견: {consensus['rating']}")
                    if consensus_source:
                        info_parts.append(f"📌 출처: {consensus_source}")
                    if info_parts:
                        st.caption(" | ".join(info_parts))

                    # 게이지 차트
                    gauge_min = min(current_price, target_price) * 0.7
                    gauge_max = max(current_price, target_price) * 1.3

                    fig_gauge = go.Figure(go.Indicator(
                        mode="gauge+number+delta",
                        value=current_price,
                        delta={
                            "reference": target_price,
                            "relative": True,
                            "valueformat": ".1%"
                        },
                        number={
                            "prefix": "₩",
                            "valueformat": ","
                        },
                        gauge={
                            "axis": {"range": [gauge_min, gauge_max]},
                            "bar": {"color": "rgba(0, 85, 164, 1.0)"},
                            "steps": [
                                {
                                    "range": [gauge_min, target_price * 0.8],
                                    "color": "rgba(232, 82, 74, 0.2)"
                                },
                                {
                                    "range": [target_price * 0.8, target_price * 1.2],
                                    "color": "rgba(77, 168, 218, 0.2)"
                                },
                                {
                                    "range": [target_price * 1.2, gauge_max],
                                    "color": "rgba(46, 125, 50, 0.2)"
                                },
                            ],
                            "threshold": {
                                "line": {"color": "rgba(232, 82, 74, 1.0)", "width": 3},
                                "thickness": 0.8,
                                "value": target_price
                            },
                        },
                        title={"text": "현재가 vs 목표가"},
                    ))
                    fig_gauge.update_layout(
                        height=300,
                        paper_bgcolor="rgba(242, 242, 242, 1.0)"
                    )
                    st.plotly_chart(fig_gauge, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})

                else:
                    # 조회 실패 시 상세 안내
                    st.warning("📭 컨센서스 목표주가를 가져올 수 없습니다.")
                    if consensus_errors:
                        with st.expander("🔍 상세 오류 확인"):
                            for err in consensus_errors:
                                st.caption(f"⚠️ {err}")
                            st.caption(
                                "💡 소형주·신규상장주는 애널리스트 커버리지가 "
                                "없을 수 있습니다."
                            )

            # ── 3-2. PER 기반 적정가 (우측) ──────────────────────────
            with col2:
                st.markdown("##### 📐 PER 기반 적정가")

                if fair_per:
                    pers = sorted(fair_per.keys())
                    vals = [fair_per[p] for p in pers]
                    colors = [
                        "#2E7D32" if v > current_price else "#E8524A"
                        for v in vals
                    ]

                    fig_per = go.Figure()
                    fig_per.add_trace(go.Bar(
                        x=[f"PER {p}배" for p in pers],
                        y=vals,
                        marker_color=colors,
                        text=[f"{v:,}원" for v in vals],
                        textposition="outside"
                    ))
                    fig_per.add_hline(
                        y=current_price,
                        line_dash="dash",
                        line_color="#E8524A",
                        annotation_text=f"현재가 {current_price:,}원"
                    )
                    fig_per.update_layout(
                        height=300,
                        plot_bgcolor="white",
                        paper_bgcolor="#F2F2F2",
                        yaxis_title="원",
                        showlegend=False
                    )
                    st.plotly_chart(fig_per, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})

                    # PER 적정가 요약 테이블
                    per_table = []
                    for p in pers:
                        v = fair_per[p]
                        gap = (v / current_price - 1) * 100
                        status = "🔺 저평가" if v > current_price else "🔻 고평가"
                        per_table.append({
                            "방법": f"PER {p}배",
                            "적정가": f"{v:,}원",
                            "괴리율": f"{gap:+.1f}%",
                            "판단": status
                        })
                    st.dataframe(
                        pd.DataFrame(per_table),
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    if not ni or ni <= 0:
                        st.info("📭 당기순이익이 음수이거나 없어 EPS 계산 불가")
                    else:
                        st.info("📭 발행주식수 정보가 없어 EPS 계산 불가")

            # ── 3-3. PBR 기반 적정가 (전체 너비) ─────────────────────
            if fair_pbr:
                st.markdown("##### 📐 PBR 기반 적정가")
                pbrs = sorted(fair_pbr.keys())
                vals = [fair_pbr[p] for p in pbrs]
                colors = [
                    "#2E7D32" if v > current_price else "#E8524A"
                    for v in vals
                ]

                fig_pbr = go.Figure()
                fig_pbr.add_trace(go.Bar(
                    x=[f"PBR {p}배" for p in pbrs],
                    y=vals,
                    marker_color=colors,
                    text=[f"{v:,}원" for v in vals],
                    textposition="outside"
                ))
                fig_pbr.add_hline(
                    y=current_price,
                    line_dash="dash",
                    line_color="#E8524A",
                    annotation_text=f"현재가 {current_price:,}원"
                )
                fig_pbr.update_layout(
                    height=300,
                    plot_bgcolor="white",
                    paper_bgcolor="#F2F2F2",
                    yaxis_title="원",
                    showlegend=False
                )
                st.plotly_chart(fig_pbr, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})

                # PBR 적정가 요약 테이블
                pbr_table = []
                for p in pbrs:
                    v = fair_pbr[p]
                    gap = (v / current_price - 1) * 100
                    status = "🔺 저평가" if v > current_price else "🔻 고평가"
                    pbr_table.append({
                        "방법": f"PBR {p}배",
                        "적정가": f"{v:,}원",
                        "괴리율": f"{gap:+.1f}%",
                        "판단": status
                    })
                st.dataframe(
                    pd.DataFrame(pbr_table),
                    hide_index=True,
                    use_container_width=True
                )

            # ── 3-4. EPS / BPS 요약 정보 ────────────────────────────
            if eps or bps:
                st.markdown("---")
                st.markdown("##### 📋 기초 지표 요약")
                mc1, mc2, mc3, mc4 = st.columns(4)
                with mc1:
                    if eps:
                        st.metric("EPS (주당순이익)", f"{eps:,.0f}원")
                    else:
                        st.metric("EPS", "N/A")
                with mc2:
                    if bps:
                        st.metric("BPS (주당순자산)", f"{bps:,.0f}원")
                    else:
                        st.metric("BPS", "N/A")
                with mc3:
                    if eps and eps > 0 and current_price > 0:
                        current_per = current_price / eps
                        st.metric("현재 PER", f"{current_per:.1f}배")
                    else:
                        st.metric("현재 PER", "N/A")
                with mc4:
                    if bps and bps > 0 and current_price > 0:
                        current_pbr = current_price / bps
                        st.metric("현재 PBR", f"{current_pbr:.2f}배")
                    else:
                        st.metric("현재 PBR", "N/A")

        else:
            st.warning("⚠️ 주가 정보가 없습니다. 종목 조회를 다시 시도해주세요.")

    else:
        st.info("👈 사이드바에서 재무제표 조회를 먼저 실행해주세요.")

with tab4:
    st.markdown("### 🔄 투자자별 매매동향")
    if st.session_state.selected_corp:
        ticker = st.session_state.selected_corp["stock_code"]
        trade_pages = st.selectbox("📅 조회 기간",["최근 1개월 (1p)","최근 2개월 (2p)","최근 3개월 (3p)","최근 6개월 (6p)"], index=2, key="trade_pages")
        n_pages = int(trade_pages.split("(")[1].split("p")[0]); cache_key_trade = f"trade_{ticker}_{n_pages}"
        if st.session_state.get("_trade_cache_key") != cache_key_trade:
            with st.spinner(f"📡 매매동향 ({n_pages}p)..."):
                all_rows = []; success = False; err_msg = ""
                for page in range(1, n_pages + 1):
                    try:
                        resp = requests.get(f"https://finance.naver.com/item/frgn.naver?code={ticker}&page={page}", headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                        from io import StringIO; dfs = pd.read_html(StringIO(resp.text))
                        for df_c in dfs:
                            if len(df_c) > 5 and len(df_c.columns) >= 6: df_c = df_c.dropna(how="all"); all_rows.append(df_c) if len(df_c) > 3 else None; success = True
                    except Exception as e: err_msg = str(e)
                if success and all_rows: st.session_state["_trade_raw"] = pd.concat(all_rows, ignore_index=True).dropna(how="all"); st.session_state["_trade_err"] = None
                else: st.session_state["_trade_raw"] = None; st.session_state["_trade_err"] = err_msg or "데이터 없음"
                st.session_state["_trade_cache_key"] = cache_key_trade
        trade_df = st.session_state.get("_trade_raw"); trade_err = st.session_state.get("_trade_err")
        if trade_df is not None and len(trade_df) > 0:
            if isinstance(trade_df.columns, pd.MultiIndex): trade_df.columns = range(len(trade_df.columns))
            cols = trade_df.columns.tolist()
            if len(cols) >= 9: col_map = {"날짜":0,"종가":1,"전일비":2,"등락률":3,"거래량":4,"기관":5,"외국인":6,"보유주수":7,"보유율":8}
            elif len(cols) >= 7: col_map = {"날짜":0,"종가":1,"전일비":2,"거래량":3,"기관":4,"외국인":5,"보유율":6}
            else: col_map = {}
            if "기관" in col_map and "외국인" in col_map:
                df = trade_df.copy()
                try:
                    date_col = df[col_map["날짜"]].astype(str).str.strip(); date_col = date_col[date_col.str.match(r'^\d{4}')]
                    df = df.loc[date_col.index]; df["_date"] = pd.to_datetime(date_col, errors="coerce")
                    df = df.dropna(subset=["_date"]).sort_values("_date").reset_index(drop=True); st.session_state["_trade_data"] = df
                except Exception as e: st.error(f"날짜 파싱 실패: {e}"); df = pd.DataFrame()
                def safe_int(val):
                    try: return int(float(str(val).replace(",","").replace("+","").strip()))
                    except: return 0
                df["_기관"] = df[col_map["기관"]].apply(safe_int); df["_외국인"] = df[col_map["외국인"]].apply(safe_int); df["_개인"] = -(df["_기관"] + df["_외국인"])
                if len(df) > 0:
                    st.markdown("#### 📈 누적 순매수 추이"); fig_cum = go.Figure()
                    for name, col, color in [("기관","_기관","#0055A4"),("외국인","_외국인","#E8524A"),("개인(추정)","_개인","#4DA8DA")]:
                        fig_cum.add_trace(go.Scatter(x=df["_date"], y=df[col].cumsum(), name=name, mode="lines", line=dict(color=color, width=2.5)))
                    fig_cum.add_hline(y=0, line_dash="dot", line_color="gray")
                    fig_cum.update_layout(height=420, plot_bgcolor="white", paper_bgcolor="#F2F2F2", yaxis_title="주 (누적)"); st.plotly_chart(fig_cum, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
                    st.markdown("#### 📊 일별 순매수 (최근 30일)"); recent = df.tail(30); fig_d = go.Figure()
                    for name, col, color in [("기관","_기관","#0055A4"),("외국인","_외국인","#E8524A")]:
                        fig_d.add_trace(go.Bar(x=recent["_date"], y=recent[col], name=name, marker_color=color, opacity=0.7))
                    fig_d.add_hline(y=0, line_color="gray"); fig_d.update_layout(barmode="group", height=350, plot_bgcolor="white", paper_bgcolor="#F2F2F2", yaxis_title="주")
                    st.plotly_chart(fig_d, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
                    mc1,mc2,mc3 = st.columns(3)
                    for w,n,c in [(mc1,"기관","_기관"),(mc2,"외국인","_외국인"),(mc3,"개인(추정)","_개인")]: t=df[c].sum(); w.metric(n, f"{t:+,}주", "순매수" if t>0 else "순매도")
                    if "보유율" in col_map:
                        def sf(v):
                            try: return float(str(v).replace(",","").replace("%","").strip())
                            except: return None
                        df["_보유율"] = df[col_map["보유율"]].apply(sf); dr = df.dropna(subset=["_보유율"])
                        if len(dr) > 0:
                            st.markdown("#### 📊 외국인 보유율 추이")
                            fig_r = go.Figure(go.Scatter(x=dr["_date"],y=dr["_보유율"],mode="lines+markers",line=dict(color="#E8524A",width=2),marker=dict(size=4)))
                            fig_r.update_layout(height=300,plot_bgcolor="white",paper_bgcolor="#F2F2F2",yaxis_title="%"); st.plotly_chart(fig_r, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
                    with st.expander("📋 상세 데이터"):

                        show=df[["_date","_기관","_외국인","_개인"]].copy(); show.columns=["날짜","기관","외국인","개인(추정)"]; show["날짜"]=show["날짜"].dt.strftime("%Y-%m-%d")
                        st.dataframe(show.tail(40),use_container_width=True,hide_index=True)
            else: st.warning("컬럼 매핑 실패")
        elif trade_err: st.error(f"⚠️ {trade_err}")
        else: st.warning("데이터 없음")
    else: st.info("👈 종목을 선택해주세요.")

with tab5:
    st.markdown("### 🏢 동종업계 비교")
    if st.session_state.selected_corp and st.session_state.dart:
        corp = st.session_state.selected_corp; my_ticker = corp["stock_code"]
        auto_sector = st.session_state.get("_auto_sector", ""); auto_peers = st.session_state.get("_auto_peers", {})
        if auto_sector: st.info(f"🔍 **자동 감지 업종**: {auto_sector} ({len(auto_peers)}개 동종 종목)")
        my_themes = [tn for tn, ti in THEME_DB.items() if my_ticker in ti["tickers"]]
        st.markdown("#### 🎯 추천 비교 종목")
        if my_themes:
            for theme in my_themes:
                ti = THEME_DB[theme]; peers = {k:v for k,v in ti["tickers"].items() if k != my_ticker}
                st.info(f"**{theme}** — {ti['desc']}\n\n{' / '.join([f'{v}(`{k}`)' for k,v in list(peers.items())[:6]])}\n\n📦 관련 ETF: {ti['etf']}")
        elif auto_peers: st.info(f"**{auto_sector}** (네이버 업종 자동감지)\n\n{' / '.join([f'{v}(`{k}`)' for k,v in list(auto_peers.items())[:8]])}")
        else: st.caption(f"'{corp['corp_name']}'의 동종업계를 찾지 못했습니다.")
        st.markdown("#### 📂 비교 종목 선택")
        source_options = ["직접 입력"] + list(THEME_DB.keys())
        if auto_peers: source_options.insert(1, f"🔍 자동감지: {auto_sector}")
        sel_theme = st.selectbox("비교 소스", source_options, key="sel_theme")
        if sel_theme.startswith("🔍 자동감지") and auto_peers:
            theme_opts = [f"{v} ({k})" for k,v in auto_peers.items()]
            selected_peers = st.multiselect("비교할 종목 (최대 5개)", theme_opts, default=theme_opts[:4], key="auto_peers_sel")
            peer_tickers = [s[s.rfind("(")+1:s.rfind(")")] for s in selected_peers if s.rfind("(")!=-1 and s[s.rfind("(")+1:s.rfind(")")].isdigit()]
        elif sel_theme != "직접 입력" and sel_theme in THEME_DB:
            ti = THEME_DB[sel_theme]; theme_opts = [f"{v} ({k})" for k,v in ti["tickers"].items() if k != my_ticker]
            selected_peers = st.multiselect("비교할 종목 (최대 5개)", theme_opts, default=theme_opts[:3], key="theme_peers")
            peer_tickers = [s[s.rfind("(")+1:s.rfind(")")] for s in selected_peers if s.rfind("(")!=-1 and s[s.rfind("(")+1:s.rfind(")")].isdigit()]
        else:
            st.caption("종목코드를 쉼표로 입력 (예: 005930, 000660)")
            peer_input = st.text_input("종목코드", placeholder="005930, 000660", key="peer_input")
            peer_tickers = [t.strip() for t in peer_input.split(",") if t.strip()] if peer_input else []
        if st.button("📊 비교 분석 실행", type="primary", key="peer_btn", use_container_width=True):
            if not peer_tickers: st.warning("비교할 종목을 선택해주세요.")
            else:
                all_tickers = [my_ticker] + peer_tickers[:5]; all_data = {}; cl = st.session_state.corp_list; progress = st.progress(0)
                for idx, tk in enumerate(all_tickers):
                    progress.progress((idx+1)/len(all_tickers), f"📡 {tk} 조회 중...")
                    try:
                        matched = cl[cl["stock_code"] == tk]
                        if len(matched) == 0: st.caption(f"⚠️ {tk}: 못 찾음"); continue
                        cc = matched.iloc[0]["corp_code"]; cn = matched.iloc[0]["corp_name"]
                        df = st.session_state.dart.finstate_all(cc, year, reprt_code=rcode)
                        if df is not None and len(df) > 0:
                            for col in df.columns:
                                try:
                                    if str(df[col].dtype) == "string": df[col] = df[col].astype(object)
                                except: pass
                            vals, _ = extract_from_df(df); p, s, _, _ = fetch_stock_info(tk)
                            prev_vals = {} 
                            rev=vals.get("매출액"); oi=vals.get("영업이익"); ni=vals.get("당기순이익"); ta=vals.get("자산총계"); tl=vals.get("부채총계"); te=vals.get("자본총계")
                            row = {"종목": cn, "코드": tk, "매출액": rev, "영업이익": oi, "당기순이익": ni}
                            row["영업이익률"] = round(oi/rev*100, 1) if rev and oi and rev!=0 else None
                            row["순이익률"] = round(ni/rev*100, 1) if rev and ni and rev!=0 else None
                            row["ROE"] = round(ni/te*100, 1) if ni and te and te!=0 else None
                            row["ROA"] = round(ni/ta*100, 1) if ni and ta and ta!=0 else None
                            row["부채비율"] = round(tl/te*100, 1) if tl and te and te!=0 else None
                            cogs_v=vals.get("매출원가"); rev_v=vals.get("매출액")
                            ar_c=vals.get("매출채권");   ar_p=(prev_vals or {}).get("매출채권")
                            inv_c=vals.get("재고자산");  inv_p=(prev_vals or {}).get("재고자산")
                            ap_c=vals.get("매입채무");   ap_p=(prev_vals or {}).get("매입채무")
                            def _avg(a,b): return (a+b)/2 if a is not None and b is not None else a
                            avg_inv=_avg(inv_c,inv_p); avg_ar=_avg(ar_c,ar_p); avg_ap=_avg(ap_c,ap_p)
                            _DIO=round(avg_inv/cogs_v*365,1) if avg_inv is not None and cogs_v not in (None,0) else None
                            _DSO=round(avg_ar/rev_v*365,1)   if avg_ar  is not None and rev_v  not in (None,0) else None
                            _DPO=round(avg_ap/cogs_v*365,1)  if avg_ap  is not None and cogs_v not in (None,0) else None
                            row["DIO"]=_DIO; row["DSO"]=_DSO; row["DPO"]=_DPO
                            row["CCC"]=round(_DIO+_DSO-_DPO,1) if (_DIO is not None and _DSO is not None and _DPO is not None) else None
                            if p and p>0 and s and s>0:
                                eps=ni/s if ni else None; bps=te/s if te else None
                                row["PER"]=round(p/eps, 1) if eps and eps>0 else None; row["PBR"]=round(p/bps, 1) if bps and bps>0 else None; row["시가총액"]=p*s
                            else: row["PER"]=None; row["PBR"]=None; row["시가총액"]=None
                            all_data[tk] = row
                    except Exception as e: st.caption(f"⚠️ {tk}: {str(e)[:50]}")
                progress.empty()
                if all_data: st.session_state["_peer_data"] = all_data
        peer_data = st.session_state.get("_peer_data")
        if peer_data and len(peer_data) > 0:
            pdf = pd.DataFrame(peer_data.values()); st.markdown("#### 📋 비교 테이블"); display_df = pdf.copy()
            for c in ["매출액","영업이익","당기순이익","시가총액"]:
                if c in display_df.columns: display_df[c] = display_df[c].apply(lambda x: fmt_amt(x) if pd.notna(x) else "N/A")
            for c in ["영업이익률","순이익률","ROE","ROA","부채비율"]:
                if c in display_df.columns: display_df[c] = display_df[c].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
            for c in ["PER","PBR"]:
                if c in display_df.columns: display_df[c] = display_df[c].apply(lambda x: f"{x:.1f}배" if pd.notna(x) else "N/A")
            for c in ["DIO","DSO","DPO","CCC"]:
                if c in display_df.columns: display_df[c] = display_df[c].apply(lambda x: f"{x:.1f}일" if pd.notna(x) else "N/A")
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            st.markdown("#### 📊 수익성 비교"); names = pdf["종목"].tolist(); colors = ["#0055A4","#E8524A","#4DA8DA","#F4A261","#9C27B0","#2E7D32"]
            fig_comp = make_subplots(rows=1, cols=3, subplot_titles=["영업이익률(%)", "ROE(%)", "PER(배)"])
            for i, metric in enumerate(["영업이익률","ROE","PER"]):
                vals = pdf[metric].tolist() if metric in pdf.columns else [None]*len(names)
                fig_comp.add_trace(go.Bar(x=names, y=[v if pd.notna(v) else 0 for v in vals], marker_color=[colors[j%len(colors)] for j in range(len(names))],
                    showlegend=False, text=[f"{v:.1f}" if pd.notna(v) else "N/A" for v in vals], textposition="outside"), row=1, col=i+1)
            fig_comp.update_layout(height=400, plot_bgcolor="white", paper_bgcolor="#F2F2F2")
            st.plotly_chart(fig_comp, use_container_width=True, key="peer_fig_comp", config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
            st.markdown("#### 🎯 종합 레이더"); categories = ["영업이익률","순이익률","ROE","ROA"]; fig_r = go.Figure()
            for idx, (_, row) in enumerate(pdf.iterrows()):
                vr = [row.get(c, 0) if pd.notna(row.get(c)) and row.get(c, 0) > -50 else 0 for c in categories]; vr.append(vr[0])
                fig_r.add_trace(go.Scatterpolar(r=vr, theta=categories+[categories[0]], fill="toself", name=row["종목"], line_color=colors[idx%len(colors)], opacity=0.6))
            fig_r.update_layout(polar=dict(radialaxis=dict(visible=True)), height=450, paper_bgcolor="#F2F2F2")
            st.plotly_chart(fig_r, use_container_width=True, key="peer_fig_radar", config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
            # ── CCC 비교 ──────────────────────────────────────────────
            ccc_cols = ["DIO","DSO","DPO","CCC"]
            if any(c in pdf.columns for c in ccc_cols):
                st.markdown("#### 🔄 운전자본 효율성 (CCC) 비교")
                ccc_df = pdf[["종목"] + [c for c in ccc_cols if c in pdf.columns]].copy()
                for c in ccc_cols:
                    if c in ccc_df.columns:
                        ccc_df[c] = ccc_df[c].apply(lambda x: f"{x:.1f}일" if pd.notna(x) else "N/A")
                st.dataframe(ccc_df, use_container_width=True, hide_index=True)
                if "CCC" in pdf.columns:
                    fig_ccc = go.Figure()
                    ccc_vals = pdf["CCC"].tolist(); ccc_names = pdf["종목"].tolist()
                    bar_colors = ["#1a7a4a" if (v is not None and pd.notna(v) and v < 60)
                                  else "#c05000" if (v is not None and pd.notna(v) and v >= 120)
                                  else "#b8860b" for v in ccc_vals]
                    fig_ccc.add_trace(go.Bar(
                        x=ccc_names,
                        y=[v if (v is not None and pd.notna(v)) else 0 for v in ccc_vals],
                        marker_color=bar_colors,
                        text=[f"{v:.1f}일" if (v is not None and pd.notna(v)) else "N/A" for v in ccc_vals],
                        textposition="outside"))
                    fig_ccc.update_layout(
                        height=350, yaxis_title="CCC (일)",
                        plot_bgcolor="white", paper_bgcolor="#F2F2F2",
                        margin=dict(l=10,r=10,t=30,b=10))
                    fig_ccc.add_hline(y=60,  line_dash="dash", line_color="#b8860b", annotation_text="60일 (주의)")
                    fig_ccc.add_hline(y=120, line_dash="dash", line_color="#a00000", annotation_text="120일 (위험)")
                    st.plotly_chart(fig_ccc, use_container_width=True, key="peer_fig_ccc",
                        config={"scrollZoom":False,"displayModeBar":False,"staticPlot":True})
                    st.caption("💡 CCC 낮을수록(음수면 최고) 현금흐름 우수 | 🟢 <60일 🟡 60~120일 🔴 >120일")
    else: st.info("👈 재무제표 조회를 먼저 실행해주세요.")


with tab6:
    st.markdown("### 📰 공시 / 뉴스")
    if st.session_state.selected_corp and st.session_state.dart:
        corp = st.session_state.selected_corp; t6_1, t6_2 = st.tabs(["📋 DART 공시", "📰 뉴스"])
        with t6_1:
            st.markdown("#### 📋 최근 DART 공시")
            dart_period = st.selectbox("조회 기간", ["최근 1개월","최근 3개월","최근 6개월","최근 1년"], index=1, key="dart_period")
            dart_days = {"최근 1개월":30,"최근 3개월":90,"최근 6개월":180,"최근 1년":365}[dart_period]; cache_key_dart = f"dart_{corp['corp_code']}_{dart_days}"
            if st.session_state.get("_dart_list_key") != cache_key_dart:
                with st.spinner("📡 DART 공시 조회 중..."):
                    try:
                        end_d = datetime.now(); start_d = end_d - timedelta(days=dart_days)
                        disc_list = st.session_state.dart.list(corp['corp_code'], start=start_d.strftime("%Y%m%d"), end=end_d.strftime("%Y%m%d"))
                        st.session_state["_dart_list"] = disc_list if disc_list is not None and len(disc_list)>0 else None
                    except Exception as e: st.session_state["_dart_list"] = None; st.error(f"실패: {e}")
                    st.session_state["_dart_list_key"] = cache_key_dart
            disc = st.session_state.get("_dart_list")
            if disc is not None and len(disc) > 0:
                st.success(f"📋 총 {len(disc)}건"); sel_f = st.selectbox("필터", ["전체","📊 정기보고서","⚡ 주요공시"], key="disc_f")
                if sel_f=="📊 정기보고서": disc_f = disc[disc["report_nm"].str.contains("사업보고서|분기보고서|반기보고서|감사보고서", na=False)]
                elif sel_f=="⚡ 주요공시": disc_f = disc[disc["report_nm"].str.contains("주요|공정공시|임원|최대주주|자기주식|증자|전환|합병", na=False)]
                else: disc_f = disc
                if len(disc_f) > 0:
                    show_c = [c for c in ["rcept_dt","report_nm","flr_nm","rcept_no"] if c in disc_f.columns]
                    disp = disc_f[show_c].copy().rename(columns={"rcept_dt":"접수일","report_nm":"공시명","flr_nm":"제출인","rcept_no":"접수번호"})
                    if "접수번호" in disp.columns: disp["DART링크"] = disp["접수번호"].apply(lambda x: f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x}"); disp = disp.drop(columns=["접수번호"])
                    st.dataframe(disp.head(50), use_container_width=True, hide_index=True, column_config={"DART링크": st.column_config.LinkColumn("DART링크", display_text="📄 공시보기")})
                    if "rcept_dt" in disc.columns:
                        dm = disc.copy(); dm["월"] = pd.to_datetime(dm["rcept_dt"], errors="coerce").dt.to_period("M").astype(str)
                        mc = dm.groupby("월").size().reset_index(name="건수")
                        if len(mc) > 1:
                            st.markdown("#### 📊 월별 공시 건수")
                            fig_d = go.Figure(go.Bar(x=mc["월"],y=mc["건수"],marker_color="#0055A4",text=mc["건수"],textposition="outside"))
                            fig_d.update_layout(height=300,plot_bgcolor="white",paper_bgcolor="#F2F2F2"); st.plotly_chart(fig_d, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False, 'staticPlot': True})
            else: st.info("공시 없음")
        with t6_2:
            st.markdown("#### 📰 관련 뉴스"); ticker = corp["stock_code"]; corp_name = corp["corp_name"]; import urllib.parse
            st.markdown(f"""<div style='display:flex; gap:10px; flex-wrap:wrap; margin-bottom:20px;'>
                <a href='https://finance.naver.com/item/news.naver?code={ticker}' target='_blank' style='flex:1; min-width:180px; padding:15px; background:linear-gradient(135deg,#e8f4fd,#d1ecf9); border-radius:10px; text-decoration:none; color:#0055A4; border:1px solid #b8daff; text-align:center;'><b>📊 네이버 증권</b><br><span style='font-size:11px;'>종목 뉴스/공시</span></a>
                <a href='https://search.naver.com/search.naver?where=news&query={urllib.parse.quote(corp_name)}&sort=1' target='_blank' style='flex:1; min-width:180px; padding:15px; background:linear-gradient(135deg,#e8fde8,#d1f9d1); border-radius:10px; text-decoration:none; color:#2E7D32; border:1px solid #b8dfb8; text-align:center;'><b>🔍 네이버 검색</b><br><span style='font-size:11px;'>최신순 뉴스</span></a>
                <a href='https://www.google.com/search?q={urllib.parse.quote(corp_name)}+주가&tbm=nws' target='_blank' style='flex:1; min-width:180px; padding:15px; background:linear-gradient(135deg,#fde8e8,#f9d1d1); border-radius:10px; text-decoration:none; color:#C62828; border:1px solid #dfb8b8; text-align:center;'><b>🌐 구글 뉴스</b><br><span style='font-size:11px;'>글로벌 검색</span></a></div>""", unsafe_allow_html=True)
            cache_key_news = f"news_{ticker}"
            if st.session_state.get("_news_key") != cache_key_news:
                with st.spinner("📡 뉴스 수집 중..."):
                    news_list = []
                    try:
                        from bs4 import BeautifulSoup; headers_nv = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                        for pg in range(1, 4):
                            resp_news = requests.get(f"https://finance.naver.com/item/news_news.naver?code={ticker}&page={pg}&sm=title_entity_id.basic&clusterId=", headers=headers_nv, timeout=5)
                            if resp_news.status_code == 200:
                                soup = BeautifulSoup(resp_news.text, "html.parser")
                                for tr in soup.select("tr"):
                                    td_title = tr.select_one("td.title"); td_info = tr.select_one("td.info"); td_date = tr.select_one("td.date")
                                    if td_title:
                                        a_tag = td_title.select_one("a")
                                        if a_tag and a_tag.get_text(strip=True):
                                            title = a_tag.get_text(strip=True); href = a_tag.get("href","")
                                            link = f"https://finance.naver.com{href}" if href.startswith("/") else href
                                            if len(title) > 5: news_list.append({"제목":title,"링크":link,"출처":td_info.get_text(strip=True) if td_info else "","날짜":td_date.get_text(strip=True) if td_date else ""})
                    except Exception as e: st.caption(f"⚠️ {e}")
                    seen=set(); unique=[]
                    for n in news_list:
                        if n["제목"] not in seen: seen.add(n["제목"]); unique.append(n)
                    st.session_state["_news_list"] = unique[:30]; st.session_state["_news_key"] = cache_key_news
            news_list = st.session_state.get("_news_list", [])
            if news_list:
                st.success(f"📰 {len(news_list)}건")
                for i, n in enumerate(news_list[:20]):
                    meta = ""; title_text = n.get("제목", ""); link_url = n.get("링크", "")
                    if n.get("출처"): meta += f'`{n["출처"]}` '
                    if n.get("날짜"): meta += f'_{n["날짜"]}_'
                    if link_url: st.markdown(f"**{i+1}.** [{title_text}]({link_url}) {meta}")
                    else: st.markdown(f"**{i+1}.** {title_text} {meta}")
            else: st.caption("스크래핑 뉴스 없음 — 위 링크 버튼을 이용해주세요.")
    else: st.info("👈 재무제표 조회를 먼저 실행해주세요.")

with tab7:
    st.markdown("### 📋 종합 리포트")
    if st.session_state.selected_corp and st.session_state.dart:
        corp = st.session_state.selected_corp; ticker = corp["stock_code"]
        st.markdown(f"## {corp['corp_name']} ({ticker})")
        st.caption(f"📅 {year}년 {'사업' if rcode=='11011' else '3분기' if rcode=='11014' else '반기' if rcode=='11012' else '1분기'}보고서 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        st.markdown("---")
        price, shares, _, _ = fetch_stock_info(ticker)
        if price and price > 0:
            c1, c2, c3 = st.columns(3); c1.metric("💰 현재가", f"{price:,.0f}원")
            if shares and shares > 0: c2.metric("📊 시가총액", fmt_amt(price*shares)); c3.metric("📈 주식수", f"{shares:,.0f}주")
        st.markdown("### 📊 핵심 재무지표"); accts = st.session_state.accounts; ratios_data = st.session_state.ratios
        if accts is not None:
            curr = accts.get("당기", {}); rev=curr.get("매출액"); oi=curr.get("영업이익"); ni=curr.get("당기순이익")
            ta=curr.get("자산총계"); tl=curr.get("부채총계"); te=curr.get("자본총계")
            r1c1,r1c2,r1c3,r1c4=st.columns(4); r1c1.metric("매출액",fmt_amt(rev)); r1c2.metric("영업이익",fmt_amt(oi)); r1c3.metric("당기순이익",fmt_amt(ni)); r1c4.metric("자본총계",fmt_amt(te))
            opm=round(oi/rev*100,1) if rev and oi and rev!=0 else None; npm=round(ni/rev*100,1) if rev and ni and rev!=0 else None
            roe=round(ni/te*100,1) if ni and te and te!=0 else None; debt_r=round(tl/te*100,1) if tl and te and te!=0 else None
            r2c1,r2c2,r2c3,r2c4=st.columns(4); r2c1.metric("영업이익률",f"{opm}%" if opm else "N/A"); r2c2.metric("순이익률",f"{npm}%" if npm else "N/A")
            r2c3.metric("ROE",f"{roe}%" if roe else "N/A"); r2c4.metric("부채비율",f"{debt_r}%" if debt_r else "N/A")
            per=None; pbr=None
            if price and shares and shares>0:
                eps=ni/shares if ni else None; bps=te/shares if te else None; per=round(price/eps,1) if eps and eps>0 else None; pbr=round(price/bps,1) if bps and bps>0 else None
                r3c1,r3c2,r3c3,r3c4=st.columns(4); r3c1.metric("EPS",f"{eps:,.0f}원" if eps else "N/A"); r3c2.metric("BPS",f"{bps:,.0f}원" if bps else "N/A")
                r3c3.metric("PER",f"{per}배" if per else "N/A"); r3c4.metric("PBR",f"{pbr}배" if pbr else "N/A")
            st.markdown("---"); st.markdown("### 🚦 투자 시그널 종합"); signals = []
            if opm is not None:
                if opm>15: signals.append(("🟢","영업이익률",f"{opm}% — 매우 우수"))
                elif opm>8: signals.append(("🟢","영업이익률",f"{opm}% — 양호"))
                elif opm>3: signals.append(("🟡","영업이익률",f"{opm}% — 보통"))
                else: signals.append(("🔴","영업이익률",f"{opm}% — 낮음"))
            if npm is not None:
                if npm>10: signals.append(("🟢","순이익률",f"{npm}% — 우수"))
                elif npm>3: signals.append(("🟡","순이익률",f"{npm}% — 보통"))
                elif npm>0: signals.append(("🔴","순이익률",f"{npm}% — 낮음"))
                else: signals.append(("🔴","순이익률",f"{npm}% — 적자"))
            if roe is not None:
                if roe>15: signals.append(("🟢","ROE",f"{roe}% — 우수"))
                elif roe>8: signals.append(("🟡","ROE",f"{roe}% — 보통"))
                elif roe>0: signals.append(("🔴","ROE",f"{roe}% — 낮음"))
                else: signals.append(("🔴","ROE",f"{roe}% — 적자"))
            if debt_r is not None:
                if debt_r<80: signals.append(("🟢","부채비율",f"{debt_r}% — 안정"))
                elif debt_r<150: signals.append(("🟡","부채비율",f"{debt_r}% — 보통"))
                elif debt_r<250: signals.append(("🔴","부채비율",f"{debt_r}% — 높음"))
                else: signals.append(("🔴","부채비율",f"{debt_r}% — 위험"))
            if per:
                if per<10: signals.append(("🟢","PER",f"{per}배 — 저평가"))
                elif per<20: signals.append(("🟡","PER",f"{per}배 — 적정"))
                elif per<40: signals.append(("🔴","PER",f"{per}배 — 고평가"))
                else: signals.append(("🔴","PER",f"{per}배 — 매우 고평가"))
            if pbr:
                if pbr<1.0: signals.append(("🟢","PBR",f"{pbr}배 — 저평가"))
                elif pbr<2.0: signals.append(("🟡","PBR",f"{pbr}배 — 적정"))
                else: signals.append(("🔴","PBR",f"{pbr}배 — 고평가"))
            prev=accts.get("전기",{}); prev_rev=prev.get("매출액"); prev_oi=prev.get("영업이익")
            if rev and prev_rev and prev_rev!=0:
                growth=round((rev/prev_rev-1)*100,1)
                if growth>10: signals.append(("🟢","매출 성장률",f"{growth:+.1f}% — 고성장"))
                elif growth>0: signals.append(("🟡","매출 성장률",f"{growth:+.1f}% — 소폭 성장"))
                else: signals.append(("🔴","매출 성장률",f"{growth:+.1f}% — 역성장"))
            if oi and prev_oi and prev_oi!=0:
                oi_g=round((oi/prev_oi-1)*100,1)
                if oi_g>10: signals.append(("🟢","영업이익 성장",f"{oi_g:+.1f}%"))
                elif oi_g>0: signals.append(("🟡","영업이익 성장",f"{oi_g:+.1f}%"))
                else: signals.append(("🔴","영업이익 성장",f"{oi_g:+.1f}%"))
            bull=[s for s in signals if s[0]=="🟢"]; bear=[s for s in signals if s[0]=="🔴"]; neutral=[s for s in signals if s[0]=="🟡"]
            sg1,sg2,sg3=st.columns(3); sg1.metric("🟢 긍정",f"{len(bull)}개"); sg2.metric("🔴 부정",f"{len(bear)}개"); sg3.metric("🟡 중립",f"{len(neutral)}개")
            score=len(bull)-len(bear)
            if score>=3: verdict="🟢 **매우 긍정적**"; color="#28a745"
            elif score>=1: verdict="🟢 **긍정적**"; color="#5cb85c"
            elif score>=-1: verdict="🟡 **중립**"; color="#ffc107"
            elif score>=-3: verdict="🔴 **부정적**"; color="#dc3545"
            else: verdict="🔴 **매우 부정적**"; color="#c9302c"
            st.markdown(f"<div style='padding:15px;border-radius:10px;background:{color}22;border-left:5px solid {color};'><h4 style='margin:0;'>종합 판정: {verdict}</h4>"
                f"<p>긍정 {len(bull)} / 부정 {len(bear)} / 중립 {len(neutral)} → 점수: {score:+d}</p></div>", unsafe_allow_html=True)
            with st.expander("📋 시그널 상세"):
                for emoji, label, desc in signals:
                    _sc = "#2E7D32" if emoji=="🟢" else "#FF8F00" if emoji=="🟡" else "#E8524A" if emoji=="🔴" else "#999"
                    st.markdown(f"{emoji} **{label}**: <span style='font-size:1.4em;font-weight:800;color:{_sc}'>{desc}</span>", unsafe_allow_html=True)
            st.markdown("---"); st.markdown("### 🎯 적정가 분석")
            if price and shares and shares>0:
                eps=ni/shares if ni else None; bps=te/shares if te else None; raw_targets=[]; targets=[]
                if eps and eps>0:
                    for m in [8,12,15,20]: v=int(eps*m); raw_targets.append(v); targets.append({"방법":f"PER {m}배","적정가":f"{v:,}원","괴리율":f"{'🔺' if v>price else '🔻'} {(v/price-1)*100:+.1f}%"})
                if bps and bps>0:
                    for m in [0.8,1.0,1.5,2.0]: v=int(bps*m); raw_targets.append(v); targets.append({"방법":f"PBR {m}배","적정가":f"{v:,}원","괴리율":f"{'🔺' if v>price else '🔻'} {(v/price-1)*100:+.1f}%"})
                if targets: st.dataframe(pd.DataFrame(targets),use_container_width=True,hide_index=True); avg_p=sum(raw_targets)/len(raw_targets); st.markdown(f"**📌 적정가 평균: {avg_p:,.0f}원** (현재가 대비 {(avg_p/price-1)*100:+.1f}%)")
            st.markdown("---"); st.markdown("### 🔄 매매동향 요약")
            trade_data = st.session_state.get("_trade_data")
            if trade_data is not None and len(trade_data)>0:
                df_t=trade_data
                if "_기관" in df_t.columns and "_외국인" in df_t.columns:
                    inst_sum=df_t["_기관"].sum(); frgn_sum=df_t["_외국인"].sum(); indv_sum=-(inst_sum+frgn_sum)
                    tc1,tc2,tc3=st.columns(3); tc1.metric("🏛️ 기관",f"{inst_sum:+,.0f}주"); tc2.metric("🌍 외국인",f"{frgn_sum:+,.0f}주"); tc3.metric("👤 개인",f"{indv_sum:+,.0f}주")
            else: st.caption("ℹ️ 매매동향 탭 조회 후 표시됩니다.")
            st.markdown("---"); st.markdown("### 🏢 동종업계 비교")
            peer_data = st.session_state.get("_peer_data")
            if peer_data and len(peer_data)>1:
                pdf=pd.DataFrame(peer_data.values()); my_row=pdf[pdf["코드"]==ticker]
                if len(my_row)>0:
                    rankings=[]
                    for m in ["영업이익률","ROE","PER","PBR","부채비율"]:
                        if m in pdf.columns:
                            valid=pdf[pd.notna(pdf[m])].sort_values(m,ascending=(m in ["PER","PBR","부채비율"]))
                            if len(valid)>0 and ticker in list(valid["코드"]):
                                rank=list(valid["코드"]).index(ticker)+1; val=my_row.iloc[0].get(m)
                                rankings.append({"지표":m,"값":f"{val:.1f}" if pd.notna(val) else "N/A","순위":f"{rank}/{len(valid)}","평가":"✅ 상위" if rank<=len(valid)/2 else "⚠️ 하위"})
                    if rankings: st.dataframe(pd.DataFrame(rankings),use_container_width=True,hide_index=True)
            else: st.caption("ℹ️ 동종업계 탭에서 비교 분석 후 표시됩니다.")
            st.markdown("---"); st.markdown("### 💡 종합 의견"); opinions=[]
            if opm and opm>10: opinions.append("✅ 영업이익률 우수 (>10%)")
            elif opm and opm>5: opinions.append("🟡 영업이익률 보통 (5~10%)")
            elif opm is not None: opinions.append("⚠️ 영업이익률 낮음 (<5%)")
            if roe and roe>15: opinions.append("✅ ROE 우수 (>15%)")
            elif roe and roe>8: opinions.append("🟡 ROE 보통 (8~15%)")
            elif roe is not None: opinions.append("⚠️ ROE 낮음 (<8%)")
            if debt_r and debt_r<100: opinions.append("✅ 부채비율 안정 (<100%)")
            elif debt_r and debt_r<200: opinions.append("🟡 부채비율 보통 (100~200%)")
            elif debt_r is not None: opinions.append("⚠️ 부채비율 높음 (>200%)")
            if per and per<10: opinions.append("✅ PER 저평가 (<10배)")
            elif per and per<20: opinions.append("🟡 PER 적정 (10~20배)")
            elif per: opinions.append("⚠️ PER 고평가 (>20배)")
            for op in opinions:
                _oc = "#2E7D32" if "✅" in op else "#FF8F00" if "🟡" in op else "#E8524A" if "⚠️" in op else "#999"
                st.markdown(f"<div style='font-size:1.2em;font-weight:700;color:{_oc};padding:4px 0'>• {op}</div>", unsafe_allow_html=True)
            st.markdown("---"); st.markdown("### 🤖 AI 분석 코멘트")
            oai_key = st.session_state.get("openai_key", "")
            if oai_key:
                ai_cache_key = f"ai_{ticker}_{year}_{rcode}"
                if st.session_state.get("_ai_cache_key") != ai_cache_key:
                    if st.button("🤖 AI 분석 생성", type="primary", key="ai_gen_btn", use_container_width=True):
                        with st.spinner("🤖 Gemini AI 분석 중... (최대 30초)"):
                            summary = build_financial_summary(accts, ratios_data, price, shares)
                            ai_result = generate_ai_comment(corp["corp_name"], summary, oai_key)
                            st.session_state["_ai_comment"] = ai_result; st.session_state["_ai_cache_key"] = ai_cache_key
                ai_comment = st.session_state.get("_ai_comment")
                if ai_comment:
                    st.markdown("""<div style='padding:20px;background:linear-gradient(135deg,#f0f4ff,#e8f0fe);border-radius:12px;border-left:5px solid #4285f4;'>""", unsafe_allow_html=True)
                    st.markdown(ai_comment)
                    st.markdown("</div>", unsafe_allow_html=True)
                    st.caption("⚠️ AI 분석은 참고용이며, 투자 판단의 근거가 아닙니다.")
            else: st.info("🤖 사이드바 → 'AI 분석' 에서 Gemini API 키를 입력하면 AI 코멘트가 생성됩니다.")
        else: st.info("👈 재무분석 탭에서 조회를 먼저 실행해주세요.")
        st.markdown("---")
        st.markdown("<div style='padding:10px;background:#f0f0f0;border-radius:5px;font-size:11px;color:#666;'>"
            "⚠️ <b>면책조항</b>: 본 리포트는 공시 데이터 기반 자동 생성되었으며, 투자 권유가 아닙니다. 투자 결정은 본인의 판단과 책임 하에 이루어져야 합니다.</div>", unsafe_allow_html=True)
    else: st.info("👈 재무제표 조회를 먼저 실행해주세요.")

st.caption("K-IFRS v3.5 | by JR Lee")
