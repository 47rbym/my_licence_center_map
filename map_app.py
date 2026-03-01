import streamlit as st
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import pandas as pd
import numpy as np

# ページ設定
st.set_page_config(layout="wide", page_title="運転免許センター事情マップ")

@st.cache_data
def load_topo_data():
    gdf = gpd.read_file("japan_topo.json")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf

@st.cache_data
def load_pop_data():
    pop_df = pd.read_csv("population_data.csv")
    pop_df['population'] = pd.to_numeric(pop_df['population'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    pop_df['code'] = pop_df['code'].apply(lambda x: str(x).replace('N', '').split('_')[0].zfill(2) + str(x).split('_')[1].zfill(3) if '_' in str(x) else str(x).zfill(5))
    return pop_df.set_index('code')['population'].to_dict()

@st.cache_data
def load_center_data():
    try:
        df = pd.read_csv("centers.csv")
    except:
        df = pd.read_csv("centers.csv", encoding="shift-jis")
    
    # 緯度経度を数値に変換（エラーはNaNにする）
    df['Latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
    df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
    # 欠損値がある行は削除
    return df.dropna(subset=['Latitude', 'Longitude'])

# データのロード
gdf = load_topo_data()
pop_dict = load_pop_data()
centers_df = load_center_data()

# --- ページ上部のコントロールエリア ---
pref_master = gdf[['N03_001', 'N03_007']].copy()
pref_master['pref_code'] = pref_master['N03_007'].str[:2]
pref_list = pref_master.drop_duplicates('N03_001').sort_values('pref_code')['N03_001'].tolist()

# プルダウン
col1, col2 = st.columns([2, 1])
with col1:
    selected_pref = st.selectbox(
        "都道府県を選択", 
        pref_list, 
        index=pref_list.index("広島県") if "広島県" in pref_list else 0
    )

# 選択された県の人口データを抽出
selected_gdf = gdf[gdf['N03_001'] == selected_pref].copy()
selected_gdf['pop_val'] = selected_gdf['N03_007'].map(pop_dict).fillna(0)

# ノイズ（所属未定地）の除外と対数計算
calc_gdf = selected_gdf[
    (selected_gdf['N03_004'].notna()) & 
    (~selected_gdf['N03_004'].str.contains('所属未定地', na=False))
].copy()
if not calc_gdf.empty:
    pop_values = calc_gdf['pop_val'].values
    log_pops = np.log10(pop_values + 1)
    log_min, log_max = log_pops.min(), log_pops.max()
    log_diff = log_max - log_min if log_max != log_min else 1
    calc_gdf['log_ratio'] = (log_pops - log_min) / log_diff
    ratio_map = calc_gdf.set_index('N03_007')['log_ratio'].to_dict()
    selected_gdf['log_ratio'] = selected_gdf['N03_007'].map(ratio_map).fillna(0)
else:
    selected_gdf['log_ratio'] = 0

# 色分け
def get_color(ratio):
    if ratio < 0.33:
        loc = ratio / 0.33
        r, g, b = int(173 + (255-173)*loc), int(216 + (255-216)*loc), int(230 + (191-230)*loc)
    elif ratio < 0.66:
        loc = (ratio - 0.33) / 0.33
        r, g, b = 255, int(255 + (190-255)*loc), int(191 + (100-191)*loc)
    else:
        loc = (ratio - 0.66) / 0.34
        r, g, b = 255, int(190 + (130-190)*loc), int(100 + (130-100)*loc)
    return f'#{r:02x}{g:02x}{b:02x}'

# 画角の調整
if selected_pref == "東京都":
    mainland = selected_gdf[selected_gdf.geometry.centroid.y > 35.0]
    bounds = mainland.total_bounds if not mainland.empty else selected_gdf.total_bounds
else:
    bounds = selected_gdf.total_bounds

# ベース地図
m = folium.Map(
    tiles=None, 
    scrollWheelZoom=True, 
    dragging=True
)

# 追加地図
folium.TileLayer(
    tiles='https://cyberjapandata.gsi.go.jp/xyz/blank/{z}/{x}/{y}.png',
    attr='国土地理院 白地図',
    name='白地図',
    show=True,
    control=False
).add_to(m)

folium.TileLayer(
    tiles='https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png',
    attr='淡色地図',
    name='🚃交通',
    overlay=True,
    opacity=0.7,
    show=False,
    control=True
).add_to(m)

folium.TileLayer(
    tiles='https://cyberjapandata.gsi.go.jp/xyz/hillshademap/{z}/{x}/{y}.png',
    attr='陰影起伏図',
    name='⛰️地形（陰影）',
    overlay=True,
    opacity=0.3,
    show=False,
    control=True
).add_to(m)

# 人口表示
folium.GeoJson(
    selected_gdf,
    name='👥人口',
    style_function=lambda x: {
        'fillColor': get_color(x['properties'].get('log_ratio', 0)),
        'color': 'none',
        'weight': 0,
        'fillOpacity': 0.4,
        'dashArray': '5, 5',
    },
    tooltip=folium.GeoJsonTooltip(
        fields=['N03_004', 'pop_val'], 
        aliases=['市区町村名:', '人口:']
    )
).add_to(m)

# 免許センターのピン
center_layer = folium.FeatureGroup(name='🚗免許センター')
local_centers = centers_df[centers_df['address'].str.contains(selected_pref, na=False)]

for _, row in local_centers.iterrows():
    folium.Marker(
        location=[row['Latitude'], row['Longitude']],
        popup=folium.Popup(f"<b>{row['name']}</b><br>{row['address']}", max_width=300),
        icon=folium.Icon(color='red', icon='car', prefix='fa'),
        tooltip=row['name']
    ).add_to(center_layer)
center_layer.add_to(m)

folium.LayerControl(collapsed=True).add_to(m)

m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

st_folium(
    m, 
    width="97%",
    height=500,
    use_container_width=True,
    returned_objects=[]
)

st.write(" ") 
st.write(" ")