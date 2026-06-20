import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import MeasureControl
import pandas as pd
import requests
import io
import zipfile
import math
import re
import json
import os
from urllib.parse import quote


try:
    from geomag.geomag import GeoMag
    GEOMAG_OK = True
except Exception:
    GEOMAG_OK = False


# =====================================================
# CONFIGURAÇÃO
# =====================================================

st.set_page_config(
    page_title="Calculadora de Ponto de Controle",
    page_icon="🪂",
    layout="wide"
)

# Mantido para compatibilidade com seu código anterior.
# Nesta versão o mapa usa ESRI World Imagery para evitar cair no OpenStreetMap.
GOOGLE_MAPS_API_KEY = "AIzaSyC-ljD1W2lR0hNFp2U-2ItDvla-_lEJMAU"
ARQUIVO_PERFIS_VELAME = "perfis_velame.json"


# =====================================================
# TABELA NOAA READY — PRESSÃO / ALTITUDE
# =====================================================

PRESSAO_ALTITUDE_NOAA = {
    20: 30000,
    50: 28500,
    70: 27900,
    100: 27000,
    150: 25500,
    200: 24000,
    250: 22500,
    300: 21000,
    350: 19500,
    400: 18000,
    450: 16500,
    500: 15000,
    550: 13500,
    600: 12000,
    650: 10500,
    700: 9000,
    750: 7500,
    800: 6000,
    850: 4500,
    900: 3000,
    925: 2250,
    950: 1500,
    975: 750,
    1000: 0,
}


# =====================================================
# ESTADO INICIAL
# =====================================================

if "lat" not in st.session_state:
    st.session_state.lat = -17.4198

if "lon" not in st.session_state:
    st.session_state.lon = -49.5713

if "altitude_ft" not in st.session_state:
    st.session_state.altitude_ft = 1815.0

if "declinacao" not in st.session_state:
    st.session_state.declinacao = None

if "centro_mapa" not in st.session_state:
    st.session_state.centro_mapa = [st.session_state.lat, st.session_state.lon]

if "ultimo_clique_planejamento" not in st.session_state:
    st.session_state.ultimo_clique_planejamento = None

if "pontos_regua" not in st.session_state:
    st.session_state.pontos_regua = []

if "ultimo_clique_regua" not in st.session_state:
    st.session_state.ultimo_clique_regua = None

if "vento_medio_velame" not in st.session_state:
    st.session_state.vento_medio_velame = 0.0

if "direcao_media_velame" not in st.session_state:
    st.session_state.direcao_media_velame = None

if "mapa_planejamento_rev" not in st.session_state:
    st.session_state.mapa_planejamento_rev = 0

if "mapa_regua_rev" not in st.session_state:
    st.session_state.mapa_regua_rev = 0
if "pontos_controle" not in st.session_state:
    st.session_state.pontos_controle = []


# =====================================================
# FUNÇÕES GERAIS
# =====================================================

def m_para_ft(metros):
    return metros * 3.28084


def nm_para_km(nm):
    return nm * 1.852


def km_para_nm(km):
    return km / 1.852


def m_para_nm(metros):
    return metros / 1852


def kft_para_ft(kft):
    return kft * 1000


def normalizar_azimute(graus):
    return graus % 360


def contra_azimute(graus):
    return (graus + 180) % 360


def verdadeiro_para_magnetico(azimute_verdadeiro, declinacao):
    if declinacao is None:
        declinacao = 0.0
    return normalizar_azimute(azimute_verdadeiro - declinacao)


def media_circular(direcoes):
    if not direcoes:
        return None

    soma_sen = 0
    soma_cos = 0

    for d in direcoes:
        rad = math.radians(d)
        soma_sen += math.sin(rad)
        soma_cos += math.cos(rad)

    media = math.degrees(math.atan2(soma_sen, soma_cos))
    return normalizar_azimute(media)


def media_circular_ponderada(direcoes, velocidades):
    if not direcoes or not velocidades:
        return None

    soma_sen = 0
    soma_cos = 0

    for d, v in zip(direcoes, velocidades):
        rad = math.radians(d)
        soma_sen += math.sin(rad) * v
        soma_cos += math.cos(rad) * v

    media = math.degrees(math.atan2(soma_sen, soma_cos))
    return normalizar_azimute(media)


def buscar_localidade(texto):
    texto = texto.strip()

    if not texto:
        return None

    tentativas = [
        texto,
        f"{texto}, Brasil",
    ]

    if texto.lower() in ["campo grande", "campo grande ms"]:
        tentativas.insert(0, "Campo Grande, Mato Grosso do Sul, Brasil")

    if texto.lower() in ["goiania", "goiânia"]:
        tentativas.insert(0, "Goiânia, Goiás, Brasil")

    headers = {"User-Agent": "CalculadoraPQD/1.0"}

    for consulta in tentativas:
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": consulta,
                "format": "json",
                "limit": 1,
                "countrycodes": "br",
                "addressdetails": 1,
            }

            r = requests.get(url, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            dados = r.json()

            if dados:
                return {
                    "nome": dados[0].get("display_name", ""),
                    "lat": float(dados[0]["lat"]),
                    "lon": float(dados[0]["lon"]),
                }

        except Exception:
            continue

    return None
def calcular_coordenada_destino(lat, lon, distancia_km, azimute_graus):
    R = 6371.0 # Raio médio da Terra em km
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    brng = math.radians(azimute_graus)
    
    lat2 = math.asin(math.sin(lat1) * math.cos(distancia_km / R) + 
                     math.cos(lat1) * math.sin(distancia_km / R) * math.cos(brng))
    
    lon2 = lon1 + math.atan2(math.sin(brng) * math.sin(distancia_km / R) * math.cos(lat1), 
                             math.cos(distancia_km / R) - math.sin(lat1) * math.sin(lat2))
    
    return math.degrees(lat2), math.degrees(lon2)


def buscar_altitude(lat, lon):
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        dados = r.json()
        elev_m = float(dados["results"][0]["elevation"])
        return m_para_ft(elev_m)
    except Exception:
        return None


def calcular_declinacao(lat, lon, altitude_ft):
    if not GEOMAG_OK:
        return None

    try:
        gm = GeoMag()
        resultado = gm.GeoMag(lat, lon, altitude_ft)
        return float(resultado.dec)
    except Exception:
        return None


def haversine_nm(lat1, lon1, lat2, lon2):
    raio_terra_m = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distancia_m = raio_terra_m * c

    return distancia_m / 1852


def distancia_total_nm(pontos):
    if len(pontos) < 2:
        return 0.0

    total = 0.0

    for i in range(len(pontos) - 1):
        total += haversine_nm(
            pontos[i][0],
            pontos[i][1],
            pontos[i + 1][0],
            pontos[i + 1][1],
        )

    return total


# =====================================================
# WINDGRAM NOAA READY
# =====================================================

def detectar_colunas_fhr(texto):
    """
    Detecta linha:
    FHR: + 0. + 3. + 6.
    """

    for linha in texto.splitlines():
        if "FHR" in linha.upper():
            nums = re.findall(r"\+\s*(\d+)", linha)
            if nums:
                return [f"+{n}" for n in nums]

    return []


def processar_windgram(texto):
    """
    Lê linhas:
    700.mb 290@030
    700.mb 290@030 291@031 292@032
    """

    colunas = detectar_colunas_fhr(texto)

    padrao_linha = re.compile(
        r"^\s*(\d{2,4})\.?\s*mb\s+(.+)$",
        re.IGNORECASE
    )

    padrao_vento = re.compile(
        r"(\d{1,3})\s*@\s*(\d{1,3})"
    )

    registros = []

    for linha in texto.splitlines():
        linha = linha.strip()

        m = padrao_linha.match(linha)

        if not m:
            continue

        pressao = int(m.group(1))
        resto = m.group(2)

        if pressao not in PRESSAO_ALTITUDE_NOAA:
            continue

        pares = padrao_vento.findall(resto)

        if not pares:
            continue

        item = {
            "pressao_mb": pressao,
            "altitude_ft_msl": PRESSAO_ALTITUDE_NOAA[pressao],
            "valores": {}
        }

        for idx, par in enumerate(pares):
            direcao = int(par[0])
            velocidade = int(par[1])

            if colunas and idx < len(colunas):
                coluna = colunas[idx]
            else:
                coluna = f"+{idx * 3}"

            item["valores"][coluna] = {
                "direcao_graus": direcao,
                "velocidade_kt": velocidade,
            }

        registros.append(item)

    return registros, colunas


def montar_dataframe_windgram(
    registros,
    coluna,
    altitude_alvo_ft,
    altura_comandamento_ft,
    perda_comandamento_ft,
    altura_saida_ft=None,
):
    linhas = []

    topo_velame_ft_msl = altitude_alvo_ft + max(altura_comandamento_ft - perda_comandamento_ft, 0)
    topo_comandamento_ft_msl = altitude_alvo_ft + altura_comandamento_ft

    if altura_saida_ft is not None and altura_saida_ft > altura_comandamento_ft:
        topo_saida_ft_msl = altitude_alvo_ft + altura_saida_ft
    else:
        topo_saida_ft_msl = topo_comandamento_ft_msl

    for r in registros:
        if coluna not in r["valores"]:
            continue

        alt = r["altitude_ft_msl"]
        valor = r["valores"][coluna]

        altura_sobre_alvo = alt - altitude_alvo_ft

        if altitude_alvo_ft <= alt <= topo_velame_ft_msl:
            fase = "Velame aberto"
        elif topo_velame_ft_msl < alt <= topo_comandamento_ft_msl:
            fase = "Comandamento"
        elif topo_comandamento_ft_msl < alt <= topo_saida_ft_msl:
            fase = "Queda livre"
        elif alt > topo_saida_ft_msl:
            fase = "Acima da saída"
        else:
            fase = "Abaixo do alvo"

        linhas.append({
            "Altitude NOAA ft": alt,
            "Altura sobre alvo ft": altura_sobre_alvo,
            "Pressão mb": r["pressao_mb"],
            "Direção °": valor["direcao_graus"],
            "Velocidade kt": valor["velocidade_kt"],
            "Fase": fase,
        })

    df = pd.DataFrame(linhas)

    if not df.empty:
        df = df.sort_values("Altitude NOAA ft", ascending=False)

    return df


def resumo_por_fase(df, fase):
    if df.empty:
        return None

    base = df[df["Fase"] == fase].copy()

    if base.empty:
        return None

    direcoes = base["Direção °"].astype(float).tolist()
    velocidades = base["Velocidade kt"].astype(float).tolist()

    return {
        "qtd": len(base),
        "vento_medio": sum(velocidades) / len(velocidades),
        "direcao_media": media_circular(direcoes),
        "direcao_ponderada": media_circular_ponderada(direcoes, velocidades),
    }
def calcular_media_camadas_mais_baixas(df, qtd_camadas):
    if df.empty:
        return None, pd.DataFrame()

    base = df[df["Fase"] == "Velame aberto"].copy()

    if base.empty:
        return None, pd.DataFrame()

    base = base.sort_values("Altitude NOAA ft", ascending=True)

    qtd_camadas = int(qtd_camadas)

    if qtd_camadas < 1:
        qtd_camadas = 1

    if qtd_camadas > len(base):
        qtd_camadas = len(base)

    selecionadas = base.head(qtd_camadas).copy()

    direcoes = selecionadas["Direção °"].astype(float).tolist()
    velocidades = selecionadas["Velocidade kt"].astype(float).tolist()

    resumo = {
        "qtd_camadas": qtd_camadas,
        "vento_medio": sum(velocidades) / len(velocidades),
        "direcao_media": media_circular(direcoes),
        "direcao_ponderada": media_circular_ponderada(direcoes, velocidades),
    }

    return resumo, selecionadas

def estilo_fases(row):
    fase = row["Fase"]

    if fase == "Velame aberto":
        cor = "background-color: #a6ff4d"
    elif fase == "Comandamento":
        cor = "background-color: #ffd966"
    elif fase == "Queda livre":
        cor = "background-color: #6fa8dc"
    elif fase == "Acima da saída":
        cor = "background-color: #dddddd"
    else:
        cor = "background-color: #eeeeee"

    estilo = f"{cor}; color: #000000; font-weight: 600"

    return [estilo for _ in row]


# =====================================================
# FÓRMULAS A E D
# =====================================================

def calcular_d(A_kft, FS_kft, CteHz_kt, V_kt, K_kft_h):
    if A_kft <= FS_kft:
        raise ValueError("A precisa ser maior que FS.")

    if K_kft_h <= 0:
        raise ValueError("K precisa ser maior que zero.")

    vel_efetiva = CteHz_kt + V_kt

    if vel_efetiva <= 0:
        raise ValueError("CteHz + V precisa ser maior que zero.")

    return (A_kft - FS_kft) * vel_efetiva / K_kft_h


def calcular_a(D_nm, FS_kft, CteHz_kt, V_kt, K_kft_h):
    vel_efetiva = CteHz_kt + V_kt

    if vel_efetiva <= 0:
        raise ValueError("CteHz + V precisa ser maior que zero.")

    return FS_kft + (D_nm * K_kft_h) / vel_efetiva
# =====================================================
# PERFIS DE VELAME
# =====================================================

def perfis_padrao_velame():
    return [
        {
            "nome": "Perfil padrão - MMS 350 BT80",
            "constante_horizontal_kt": 23.3,
            "k_kft_h": 40.6,
            "fs_kft": 2.0,
        }
    ]


def carregar_perfis_velame():
    if not os.path.exists(ARQUIVO_PERFIS_VELAME):
        return perfis_padrao_velame()

    try:
        with open(ARQUIVO_PERFIS_VELAME, "r", encoding="utf-8") as arquivo:
            perfis = json.load(arquivo)

        if isinstance(perfis, list) and len(perfis) > 0:
            return perfis

        return perfis_padrao_velame()

    except Exception:
        return perfis_padrao_velame()


def salvar_perfis_velame(perfis):
    with open(ARQUIVO_PERFIS_VELAME, "w", encoding="utf-8") as arquivo:
        json.dump(perfis, arquivo, ensure_ascii=False, indent=4)

# =====================================================
# MAPA AUXILIAR
# =====================================================

def criar_mapa_base(location, zoom=13):
    mapa = folium.Map(
        location=location,
        zoom_start=zoom,
        tiles=None,
        control_scale=True,
    )

    # Camada base: satélite
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satélite",
        overlay=False,
        control=False,
        show=True,
    ).add_to(mapa)

    # Camada sobreposta: nomes de cidades, limites e referências
    folium.TileLayer(
        tiles="https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Reference",
        name="Nomes e limites",
        overlay=True,
        control=False,
        show=True,
    ).add_to(mapa)

    return mapa

# =====================================================
# INTERFACE
# =====================================================

st.title("🪂 Ferramenta Auxiliar de Planejamento SLOP")

st.caption(
    "Fluxo: selecionar ponto → abrir NOAA READY → colar Windgram → calcular dados auxiliares."
)

st.warning(
    "First of Heroes"
)

aba_planejamento, aba_calculos, aba_camadas, aba_dkva = st.tabs(
    [
        "Planejamento / Windgram",
        "Cálculo da Distância para Velame Aberto",
        "Calculadora dos Pontos de Controle",
        "Salto sobre o Alvo (DKVA)"
    ]
)


# =====================================================
# ABA PLANEJAMENTO
# =====================================================

with aba_planejamento:
    col_esq, col_dir = st.columns([1.15, 1])

    with col_esq:
        st.subheader("1. Alvo")

        busca = st.text_input(
            "Pesquisar localidade",
            placeholder="Ex: Campo Grande, Goiânia, Anápolis, Fazenda..."
        )

        c_busca1, c_busca2 = st.columns(2)

        with c_busca1:
            if st.button("🔎 Pesquisar local"):
                if busca.strip():
                    resultado = buscar_localidade(busca)

                    if resultado:
                        st.session_state.lat = float(resultado["lat"])
                        st.session_state.lon = float(resultado["lon"])
                        st.session_state.centro_mapa = [
                            st.session_state.lat,
                            st.session_state.lon,
                        ]
                        st.session_state.mapa_planejamento_rev += 1
                        st.success(resultado["nome"])
                        st.rerun()
                    else:
                        st.error("Local não encontrado.")

        with c_busca2:
            if st.button("📍 Buscar altitude/declinação"):
                alt = buscar_altitude(st.session_state.lat, st.session_state.lon)

                if alt is not None:
                    st.session_state.altitude_ft = round(alt, 0)
                    st.session_state.mapa_planejamento_rev += 1

                dec = calcular_declinacao(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.altitude_ft
                )

                if dec is not None:
                    st.session_state.declinacao = dec
                else:
                    st.warning("Não foi possível calcular a declinação automaticamente. Preencha manualmente.")

                st.rerun()

        c1, c2, c3 = st.columns(3)

        with c1:
            lat = st.number_input(
                "Latitude",
                value=float(st.session_state.lat),
                step=0.0001,
                format="%.6f",
                key=f"lat_planejamento_{st.session_state.mapa_planejamento_rev}",
            )

        with c2:
            lon = st.number_input(
                "Longitude",
                value=float(st.session_state.lon),
                step=0.0001,
                format="%.6f",
                key=f"lon_planejamento_{st.session_state.mapa_planejamento_rev}",
            )

        with c3:
            altitude_alvo_ft = st.number_input(
                "Altitude do alvo ft MSL",
                value=float(st.session_state.altitude_ft),
                step=50.0,
                key=f"altitude_planejamento_{st.session_state.mapa_planejamento_rev}",
            )

        st.session_state.lat = float(lat)
        st.session_state.lon = float(lon)
        st.session_state.altitude_ft = float(altitude_alvo_ft)
        st.session_state.centro_mapa = [st.session_state.lat, st.session_state.lon]

        if st.session_state.declinacao is None:
            declinacao = st.number_input(
                "Declinação magnética manual",
                value=0.0,
                step=0.1,
                key="declinacao_manual",
            )
        else:
            declinacao = st.session_state.declinacao
            st.metric("Declinação magnética", f"{declinacao:.2f}°")

        st.markdown("### Selecionar ponto no mapa")

        mapa_planejamento = criar_mapa_base(
            [st.session_state.lat, st.session_state.lon],
            zoom=13
        )

        folium.Marker(
            location=[st.session_state.lat, st.session_state.lon],
            popup="Alvo",
            tooltip="Alvo",
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(mapa_planejamento)

        resultado_mapa_planejamento = st_folium(
            mapa_planejamento,
            width=None,
            height=420,
            key=f"mapa_planejamento_{st.session_state.mapa_planejamento_rev}",
            returned_objects=["last_clicked"],
        )

        if resultado_mapa_planejamento and resultado_mapa_planejamento.get("last_clicked"):
            lat_click = float(resultado_mapa_planejamento["last_clicked"]["lat"])
            lon_click = float(resultado_mapa_planejamento["last_clicked"]["lng"])

            novo_clique = [round(lat_click, 7), round(lon_click, 7)]

            if st.session_state.ultimo_clique_planejamento != novo_clique:
                st.session_state.ultimo_clique_planejamento = novo_clique
                st.session_state.lat = lat_click
                st.session_state.lon = lon_click
                st.session_state.centro_mapa = [lat_click, lon_click]
                st.session_state.mapa_planejamento_rev += 1
                st.rerun()

        st.divider()

        st.subheader("2. Parâmetros")

        c4, c5, c6 = st.columns(3)

        with c4:
            altura_comandamento_ft = st.number_input(
                "Altura de comandamento ft",
                value=12000.0,
                step=500.0,
                key="altura_comandamento",
            )

        with c5:
            perda_comandamento_ft = st.number_input(
                "Perda no comandamento ft",
                value=1000.0,
                step=100.0,
                key="perda_comandamento",
            )

        with c6:
            altura_saida_ft = st.number_input(
                "Altura de saída ft",
                value=12000.0,
                step=500.0,
                help="Opcional. Se for igual ao comandamento, praticamente não haverá faixa de queda livre colorida.",
                key="altura_saida",
            )

        topo_velame_msl = altitude_alvo_ft + max(altura_comandamento_ft - perda_comandamento_ft, 0)
        topo_comandamento_msl = altitude_alvo_ft + altura_comandamento_ft

        st.info(
            f"Velame aberto considerado do alvo até {topo_velame_msl:,.0f} ft MSL. "
            f"Comandamento/transição até {topo_comandamento_msl:,.0f} ft MSL."
        )

        st.divider()

        st.subheader("3. NOAA READY / Windgram")

        st.link_button(
            "Abrir NOAA READY",
            "https://www.ready.noaa.gov/READYcmet.php"
        )

        st.write("Coordenadas para copiar no NOAA:")
        st.code(f"{st.session_state.lat:.6f}, {st.session_state.lon:.6f}")

        with st.expander("Instruções rápidas"):
            st.markdown(
                """
                No NOAA READY:

                1. Insira latitude e longitude.
                2. Escolha a previsão mais recente.
                3. Produto: **WINDGRAM**.
                4. Escolha o horário Zulu do lançamento.
                5. Duração: **3h**.
                6. Saída: **Text only**.
                7. Resolva o CAPTCHA no site.
                8. Copie a tabela textual e cole abaixo.
                """
            )

        texto_windgram = st.text_area(
            "Cole aqui o Windgram textual",
            height=260,
            placeholder="Ex:\nFHR: + 0.\n700.mb 290@030\n750.mb 289@029\n800.mb 286@026",
            key="windgram_texto",
        )

        if st.button("Carregar Windgram e calcular", type="primary"):
            registros, colunas = processar_windgram(texto_windgram)

            if not registros:
                st.error("Não consegui ler o Windgram. Cole linhas no formato: 700.mb 290@030")
            else:
                if not colunas:
                    colunas = list(registros[0]["valores"].keys())

                coluna = colunas[0]

                df = montar_dataframe_windgram(
                    registros=registros,
                    coluna=coluna,
                    altitude_alvo_ft=altitude_alvo_ft,
                    altura_comandamento_ft=altura_comandamento_ft,
                    perda_comandamento_ft=perda_comandamento_ft,
                    altura_saida_ft=altura_saida_ft,
                )

                resumo_velame = resumo_por_fase(df, "Velame aberto")
                resumo_queda = resumo_por_fase(df, "Queda livre")

                st.session_state.df_windgram = df
                st.session_state.resumo_velame = resumo_velame
                st.session_state.resumo_queda = resumo_queda
                st.session_state.declinacao_usada = declinacao

                if resumo_velame:
                    st.session_state.vento_medio_velame = resumo_velame["vento_medio"]
                    st.session_state.direcao_media_velame = resumo_velame["direcao_media"]

                st.success("Windgram processado com sucesso.")

    with col_dir:
        st.subheader("Resultado")

        if "df_windgram" not in st.session_state:
            st.info("Cole o Windgram e clique em calcular.")
        else:
            df = st.session_state.df_windgram
            resumo_velame = st.session_state.resumo_velame
            resumo_queda = st.session_state.resumo_queda
            declinacao = st.session_state.declinacao_usada

            if resumo_velame:
                vento = resumo_velame["vento_medio"]
                direcao_vento = resumo_velame["direcao_media"]
                direcao_ponderada = resumo_velame["direcao_ponderada"]

                azimute_referencia_verdadeiro = direcao_vento
                azimute_referencia_magnetico = verdadeiro_para_magnetico(
                    azimute_referencia_verdadeiro,
                    declinacao
                )

                r1, r2 = st.columns(2)

                with r1:
                    st.metric("Média dos Ventos de Camada", f"{vento:.1f} kt")
                    st.metric("Direção média dos ventos", f"{direcao_vento:.0f}°")

                with r2:
                    st.metric("Azimute de Navegação / Entrada de Cauda", f"{azimute_referencia_magnetico:.0f}°")
                    st.metric("Entrada de Nariz", f"{contra_azimute(azimute_referencia_magnetico):.0f}°")

                st.write(f"Referência verdadeira: **{azimute_referencia_verdadeiro:.0f}°**")
                st.write(f"Declinação aplicada: **{declinacao:.2f}°**")
                st.write(f"Direção ponderada do vento: **{direcao_ponderada:.0f}°**")
                st.write(f"Camadas de velame usadas: **{resumo_velame['qtd']}**")

            else:
                st.warning("Nenhuma camada de velame aberto foi encontrada.")

            if resumo_queda:
                with st.expander("Resumo queda livre"):
                    st.write(f"Vento médio: **{resumo_queda['vento_medio']:.1f} kt**")
                    st.write(f"Direção média: **{resumo_queda['direcao_media']:.0f}°**")
                    st.write(f"Camadas usadas: **{resumo_queda['qtd']}**")

            with st.expander("Ver tabela colorida"):
                st.dataframe(
                    df.style.apply(estilo_fases, axis=1),
                    use_container_width=True,
                    height=500
                )


# =====================================================
# ABA CÁLCULO DA DISTÂNCIA PARA VELAME ABERTO
# =====================================================

with aba_calculos:
    st.subheader("Cálculo da Distância para Velame Aberto")

    st.info(
        "Objetivo: calcular D pela fórmula: "
        "D = (A - FS) × (Constante Horizontal + Vento Médio) / K"
    )

    perfis = carregar_perfis_velame()

    nomes_perfis = [p["nome"] for p in perfis]

    perfil_escolhido_nome = st.selectbox(
        "Selecionar perfil salvo",
        nomes_perfis
    )

    perfil_escolhido = next(
        p for p in perfis if p["nome"] == perfil_escolhido_nome
    )

    st.divider()

    vento_default = float(st.session_state.vento_medio_velame)

    if vento_default <= 0:
        st.warning(
            "Ainda não há vento médio vindo da aba Planejamento / Windgram. "
            "Cole e processe o Windgram na aba anterior para preencher automaticamente."
        )

    c1, c2 = st.columns(2)

    with c1:
        A_kft = st.number_input(
            "A — Altura de abertura do paraquedas (kft)",
            value=12.0,
            step=0.1,
            help="Exemplo: 12.0 significa 12.000 ft."
        )

        FS_kft = st.number_input(
            "FS — Fator de Segurança (kft)",
            value=float(perfil_escolhido.get("fs_kft", 2.0)),
            step=0.1,
            help="Exemplo: 2.0 significa 2.000 ft."
        )

        st.warning(
            "Alerta FS: o mínimo do manual é 2 kft — "
            "1 kft para abertura do paraquedas e 1 kft para o Líder chegar com 1000 ft sobre o alvo."
        )

    with c2:
        CteHz = st.number_input(
            "Constante Horizontal (kt)",
            value=float(perfil_escolhido.get("constante_horizontal_kt", 23.3)),
            step=0.1
        )

        V = st.number_input(
            "Velocidade média dos ventos de camada (kt)",
            value=vento_default,
            step=0.1,
            help="Este valor vem automaticamente da aba Planejamento / Windgram."
        )

        K = st.number_input(
            "K — Constante vertical (kft/h)",
            value=float(perfil_escolhido.get("k_kft_h", 40.6)),
            step=0.1
        )

    st.divider()

    if st.button("Calcular D", type="primary"):
        try:
            if FS_kft < 2.0:
                st.error("FS abaixo de 2 kft. Ajuste o fator de segurança antes de calcular.")
            else:
                D = calcular_d(A_kft, FS_kft, CteHz, V, K)

                st.session_state.distancia_velame_aberto_nm = D
                st.session_state.fs_velame_aberto_kft = FS_kft
                st.session_state.ctehz_velame_aberto_kt = CteHz
                st.session_state.k_velame_aberto_kft_h = K

                r1, r2, r3 = st.columns(3)

                with r1:
                    st.metric("D em NM", f"{D:.3f} NM")

                with r2:
                    st.metric("D em km", f"{nm_para_km(D):.3f} km")

                with r3:
                    st.metric("D em metros", f"{D * 1852:.0f} m")

                st.success("Distância para velame aberto calculada com sucesso.")

        except Exception as e:
            st.error(str(e))

    st.divider()

    with st.expander("Salvar novo perfil"):
        with st.form("form_salvar_perfil_velame", clear_on_submit=True):
            novo_nome = st.text_input(
                "Nome do perfil",
                placeholder="Ex: MMS 350, Phantom 360, Perfil teste..."
            )

            novo_ctehz = st.number_input(
                "Constante Horizontal do perfil (kt)",
                value=23.3,
                step=0.1,
                key="novo_perfil_ctehz"
            )

            novo_k = st.number_input(
                "K do perfil (kft/h)",
                value=40.6,
                step=0.1,
                key="novo_perfil_k"
            )

            novo_fs = st.number_input(
                "FS padrão do perfil (kft)",
                value=2.0,
                step=0.1,
                key="novo_perfil_fs"
            )

            salvar = st.form_submit_button("Salvar perfil")

            if salvar:
                if not novo_nome.strip():
                    st.error("Informe um nome para o perfil.")
                else:
                    perfis.append(
                        {
                            "nome": novo_nome.strip(),
                            "constante_horizontal_kt": float(novo_ctehz),
                            "k_kft_h": float(novo_k),
                            "fs_kft": float(novo_fs),
                        }
                    )

                    salvar_perfis_velame(perfis)

                    st.success("Perfil salvo com sucesso.")
                    st.rerun()

    with st.expander("Excluir perfil salvo"):
        if len(perfis) <= 1:
            st.info("Há apenas o perfil padrão. Crie outro perfil antes de excluir.")
        else:
            perfil_excluir = st.selectbox(
                "Escolha o perfil para excluir",
                nomes_perfis,
                key="perfil_excluir"
            )

            if st.button("Excluir perfil"):
                perfis = [p for p in perfis if p["nome"] != perfil_excluir]
                salvar_perfis_velame(perfis)
                st.success("Perfil excluído.")
                st.rerun()

# =====================================================
# ABA CALCULADORA DOS PONTOS DE CONTROLE
# =====================================================

# =====================================================
# ABA CALCULADORA DOS PONTOS DE CONTROLE
# =====================================================

with aba_camadas:
    st.subheader("Calculadora dos Pontos de Controle")

    st.info(
        "Objetivo: calcular rapidamente quantas camadas mais baixas do Windgram "
        "devem ser consideradas para um ponto escolhido no terreno, com base na "
        "distância desse ponto até o alvo."
    )

    # -----------------------------
    # 1. Dados automáticos
    # -----------------------------

    st.markdown("### 1. Dados automáticos")

    D_total_nm = float(st.session_state.get("distancia_velame_aberto_nm", 0.0))
    D_total_km = nm_para_km(D_total_nm)

    if "resumo_velame" in st.session_state and st.session_state.resumo_velame:
        camadas_totais = int(st.session_state.resumo_velame["qtd"])
    else:
        camadas_totais = 0

    c_auto1, c_auto2 = st.columns(2)

    with c_auto1:
        st.metric(
            "D total",
            f"{D_total_km:.3f} km",
            help="Distância total calculada na aba de Distância para Velame Aberto."
        )
        st.caption(f"Equivalente a {D_total_nm:.3f} NM")

    with c_auto2:
        st.metric(
            "Camadas totais",
            f"{camadas_totais}",
            help="Número de camadas consideradas a partir do Windgram processado."
        )

    if D_total_nm <= 0:
        st.warning(
            "Ainda não existe D calculado. Vá na aba 'Cálculo da Distância para Velame Aberto' "
            "e calcule a distância primeiro."
        )

    if camadas_totais <= 0:
        st.warning(
            "Ainda não existem camadas vindas do Windgram. Vá na aba 'Planejamento / Windgram', "
            "cole o Windgram e processe os dados."
        )

    st.divider()

    # -----------------------------
    # 2. Entrada do usuário
    # -----------------------------

    st.markdown("### 2. Distância do ponto de controle")

    distancia_pc_km = st.number_input(
        "Distância do ponto de controle até o alvo (km)",
        value=0.0,
        step=0.1,
        min_value=0.0,
        help="Informe a distância em linha reta do ponto escolhido no terreno até o alvo."
    )

    distancia_pc_nm = km_para_nm(distancia_pc_km)

    st.caption(f"Conversão automática: {distancia_pc_km:.3f} km = {distancia_pc_nm:.3f} NM")
    FS_kft = float(st.session_state.get("fs_velame_aberto_kft", 2.0))
    CteHz = float(st.session_state.get("ctehz_velame_aberto_kt", 23.3))
    K = float(st.session_state.get("k_velame_aberto_kft_h", 40.6))

    st.divider()

    # -----------------------------
    # 3. Resultado direto
    # -----------------------------

    # -----------------------------
    # 3. Resultado direto
    # -----------------------------

    if st.button("Calcular ponto de controle", type="primary"):
        if D_total_nm <= 0:
            st.error("Calcule primeiro o D na aba de Distância para Velame Aberto.")
        elif camadas_totais <= 0:
            st.error("Processe primeiro o Windgram na aba Planejamento / Windgram.")
        elif distancia_pc_km <= 0:
            st.error("Informe a distância do ponto de controle ao alvo.")
        elif distancia_pc_nm > D_total_nm:
            st.error("A distância do ponto não pode ser maior que o D total.")
        elif "df_windgram" not in st.session_state:
            st.error("Tabela Windgram não encontrada. Processe o Windgram novamente.")
        else:
            camadas_exatas = (distancia_pc_nm * camadas_totais) / D_total_nm
            camadas_consideradas = round(camadas_exatas)
            
            if camadas_consideradas < 1:
                camadas_consideradas = 1
            if camadas_consideradas > camadas_totais:
                camadas_consideradas = camadas_totais

            resumo_pc, df_camadas_pc = calcular_media_camadas_mais_baixas(
                st.session_state.df_windgram,
                camadas_consideradas
            )

            # Salva o cálculo na memória para não sumir ao clicar em outros botões
            st.session_state.calculo_pc_atual = {
                "camadas_consideradas": camadas_consideradas,
                "resumo_pc": resumo_pc,
                "df_camadas_pc": df_camadas_pc,
                "distancia_pc_nm": distancia_pc_nm,
                "distancia_pc_km": distancia_pc_km
            }

    # ==========================================
    # EXIBIÇÃO E ADIÇÃO NO BANCO DE DADOS
    # ==========================================
    
    # Só exibe os dados se o cálculo já foi feito e está na memória
    if "calculo_pc_atual" in st.session_state:
        dados_pc = st.session_state.calculo_pc_atual
        resumo_pc = dados_pc["resumo_pc"]
        
        r1, r2 = st.columns(2)
        with r1:
            st.metric("Camadas consideradas", f"{dados_pc['camadas_consideradas']}")
        with r2:
            st.metric("Média dos ventos nessas camadas", f"{resumo_pc['vento_medio']:.1f} kt")

        st.divider()

        st.markdown("### Dados para consulta")
        d1, d2, d3 = st.columns(3)
        with d1:
            st.metric("D usado", f"{dados_pc['distancia_pc_nm']:.3f} NM")
            st.caption(f"{dados_pc['distancia_pc_km']:.3f} km")
        with d2:
            st.metric("V usado", f"{resumo_pc['vento_medio']:.1f} kt")
        with d3:
            st.metric("Direção ponderada", f"{resumo_pc['direcao_ponderada']:.0f}°")

        d4, d5, d6 = st.columns(3)
        with d4:
            st.metric("FS", f"{FS_kft:.1f} kft")
        with d5:
            st.metric("CteHz", f"{CteHz:.1f} kt")
        with d6:
            st.metric("K", f"{K:.1f} kft/h")

        st.divider()
        
        st.markdown("### Cálculo da Altura P Ctle")
        v_usado = resumo_pc['vento_medio']
        vel_efetiva = CteHz + v_usado

        if vel_efetiva > 0:
            # O cálculo original te dá o valor em kft
            w_calculado_kft = ((dados_pc['distancia_pc_nm'] * K) / vel_efetiva) + FS_kft
            
            # Multiplicamos por 1000 para converter para ft
            w_calculado_ft = w_calculado_kft * 1000
            
            # Formatação para o padrão brasileiro (trocando vírgula por ponto e vice-versa)
            w_ft_formatado = f"{w_calculado_ft:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
            st.metric(
                label="Altura P Ctle calculada",
                value=f"{w_ft_formatado} ft",
                help="Calculado a partir do D usado e média de ventos das camadas inferiores."
            )
            
            observacao_pc = st.text_input(
                "Observação / Referência Visual",
                placeholder="Ex: Curva de rio, estrada de terra...",
                key="observacao_manual_pc"
            )
            
            # Botão para salvar no banco
            if st.button("➕ Adicionar P Ctle", type="secondary"):
                novo_ponto = {
                    "ID": len(st.session_state.pontos_controle) + 1,
                    "Dist (km)": round(dados_pc['distancia_pc_km'], 3),
                    "Alt P Ctle (ft)": round(w_calculado_ft, 2), # <--- Agora salva em ft na tabela!
                    "Vento Médio (kt)": round(v_usado, 1),
                    "Camadas": dados_pc['camadas_consideradas'],
                    "Observação": observacao_pc
                }
                st.session_state.pontos_controle.append(novo_ponto)
                st.success(f"Ponto {novo_ponto['ID']} salvo com sucesso!")
                st.rerun() # Atualiza a tela instantaneamente para mostrar na tabela
                
        else:
            st.error("A velocidade efetiva (CteHz + V usado) é menor ou igual a zero.")
    # -----------------------------
    # TABELA DE REGISTROS (BANCO)
    # -----------------------------
    st.divider()
    st.markdown("### 🗂️ Pontos de Controle Registrados")

    if not st.session_state.pontos_controle:
        st.info("Nenhum ponto de controle adicionado ainda para este salto.")
    else:
        # Transforma a lista em DataFrame para ficar bonito no app
        df_banco = pd.DataFrame(st.session_state.pontos_controle)
        st.dataframe(df_banco, use_container_width=True, hide_index=True)
        
        # Opção para excluir dados se errar
        if st.button("🗑️ Limpar Todos os Pontos"):
            st.session_state.pontos_controle = []
            st.rerun()
            # -----------------------------
    # EXPORTAÇÃO KMZ
    # -----------------------------
    st.divider()
    st.markdown("### 🌍 Exportar Planejamento (Google Earth)")

    # Verifica se há D total e Windgram processado para traçar a reta
    if st.session_state.get("df_windgram") is not None and st.session_state.get("distancia_velame_aberto_nm", 0) > 0:
        
        if st.button("Gerar Arquivo KMZ", type="primary"):
            # Dados base
            lat_alvo = st.session_state.lat
            lon_alvo = st.session_state.lon
            dist_total_km = nm_para_km(st.session_state.distancia_velame_aberto_nm)
            
            # Direção do Vento (Azimute Verdadeiro calculado na aba 1)
            azimute_vento = st.session_state.resumo_velame["direcao_media"]
            
            # Ponto final da reta (Abertura do Velame)
            lat_fim, lon_fim = calcular_coordenada_destino(lat_alvo, lon_alvo, dist_total_km, azimute_vento)
            
            # Construindo o código KML
            kml_str = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Planejamento SLOP</name>
    
    <Style id="linhaEixo">
      <LineStyle>
        <color>ff0000ff</color> <width>3</width>
      </LineStyle>
    </Style>
    <Style id="iconeAlvo">
      <IconStyle>
        <Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-stars.png</href></Icon>
      </IconStyle>
    </Style>
    <Style id="iconePonto">
      <IconStyle>
        <Icon><href>http://maps.google.com/mapfiles/kml/paddle/ylw-blank.png</href></Icon>
      </IconStyle>
    </Style>

    <Placemark>
      <name>Alvo </name>
      <styleUrl>#iconeAlvo</styleUrl>
      <Point>
        <coordinates>{lon_alvo},{lat_alvo},0</coordinates>
      </Point>
    </Placemark>

    <Placemark>
      <name>Eixo de Navegação ({dist_total_km:.2f} km)</name>
      <styleUrl>#linhaEixo</styleUrl>
      <LineString>
        <extrude>1</extrude>
        <tessellate>1</tessellate>
        <coordinates>
          {lon_alvo},{lat_alvo},0
          {lon_fim},{lat_fim},0
        </coordinates>
      </LineString>
    </Placemark>

    <Placemark>
      <name>PS</name>
      <description>Ponto de Saída / Início da Navegação</description>
      <styleUrl>#iconePonto</styleUrl>
      <Point>
        <coordinates>{lon_fim},{lat_fim},0</coordinates>
      </Point>
    </Placemark>
"""
            # Marcadores dos Pontos de Controle
            for p in st.session_state.pontos_controle:
                lat_pc, lon_pc = calcular_coordenada_destino(lat_alvo, lon_alvo, p["Dist (km)"], azimute_vento)
                
                # Formatando a altura para kft com 1 casa decimal e vírgula
                altura_kft = p['Alt P Ctle (ft)'] / 1000
                altura_formatada = f"{altura_kft:.1f}".replace(".", ",")
                nome_pc = f"P Ct {p['ID']} - {altura_formatada}"
                
                obs = p.get('Observação', '')
                
                kml_str += f"""
    <Placemark>
      <name>{nome_pc}</name>
      <description>{obs}</description>
      <styleUrl>#iconePonto</styleUrl>
      <Point>
        <coordinates>{lon_pc},{lat_pc},0</coordinates>
      </Point>
    </Placemark>
"""
            
            # Fecha o XML
            kml_str += """  </Document>\n</kml>"""
            
            # Empacota em um arquivo KMZ (zip)
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr("planejamento.kml", kml_str.encode("utf-8"))
            
            kmz_bytes = zip_buffer.getvalue()
            
            # Libera o download
            st.success("KMZ gerado com sucesso!")
            st.download_button(
                label="🗺️ Baixar KMZ para Google Earth",
                data=kmz_bytes,
                file_name="Planejamento_SLOP.kmz",
                mime="application/vnd.google-earth.kmz"
            )
    else:
        st.info("Realize o cálculo da Distância Total e do Windgram nas abas anteriores para liberar a exportação.")
        # =====================================================
# ABA SALTO SOBRE O ALVO (DKVA)
# =====================================================

with aba_dkva:
    st.subheader("🎯 Planejamento para Saltos sobre o Alvo (DKVA)")
    st.info("Objetivo: Calcular a distância de lançamento (D) em metros usando a constante K=25.")

    # Verifica se já temos o vento calculado na primeira aba
    if "resumo_velame" not in st.session_state or not st.session_state.resumo_velame:
        st.warning("⚠️ Volte na aba 'Planejamento / Windgram' e processe o Windgram para obter o Vento Médio e a Direção.")
    else:
        v_usado = st.session_state.resumo_velame["vento_medio"]
        direcao_vento = st.session_state.resumo_velame["direcao_media"]
        K_alvo = 25

        st.markdown("### 1. Parâmetros")
        
        c_alvo1, c_alvo2, c_alvo3 = st.columns(3)
        
        with c_alvo1:
            st.metric("K (Constante)", f"{K_alvo}")
            
        with c_alvo2:
            st.metric("V (Vento Médio)", f"{v_usado:.1f} kt")
            
        with c_alvo3:
            A_kft = st.number_input(
                "A (Altura de abertura em kft)",
                value=1.2,
                step=0.1,
                help="Ex: 1.2 significa 1.200 pés."
            )

        st.divider()
        st.markdown("### 2. Resultado")

        # Cálculo da fórmula D = K * V * A (Resultado em metros)
        d_metros = K_alvo * v_usado * A_kft
        d_km = d_metros / 1000

        r1, r2, r3 = st.columns(3)
        with r1:
            st.metric("Distância (D)", f"{d_metros:.0f} metros")
        with r2:
            st.metric("Direção do Vento", f"{direcao_vento:.0f}°")
        with r3:
            st.metric("Eixo de Navegação (Nariz)", f"{contra_azimute(direcao_vento):.0f}°")

        # -----------------------------
        # EXPORTAÇÃO KMZ DO DKVA
        # -----------------------------
        st.divider()
        st.markdown("### 🌍 Exportar Planejamento (Google Earth)")
        
        if st.button("Gerar Arquivo KMZ (DKVA)", type="primary", key="btn_kmz_dkva"):
            # Coordenadas Iniciais e Finais
            lat_alvo = st.session_state.lat
            lon_alvo = st.session_state.lon
            lat_pl, lon_pl = calcular_coordenada_destino(lat_alvo, lon_alvo, d_km, direcao_vento)
            
            kml_dkva = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Planejamento DKVA</name>
    <Style id="linhaEixo">
      <LineStyle><color>ff0000ff</color><width>3</width></LineStyle>
    </Style>
    <Style id="iconeAlvo">
      <IconStyle><Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-stars.png</href></Icon></IconStyle>
    </Style>
    <Style id="iconePonto">
      <IconStyle><Icon><href>http://maps.google.com/mapfiles/kml/paddle/ylw-blank.png</href></Icon></IconStyle>
    </Style>

    <Placemark>
      <name>Alvo</name>
      <styleUrl>#iconeAlvo</styleUrl>
      <Point><coordinates>{lon_alvo},{lat_alvo},0</coordinates></Point>
    </Placemark>

    <Placemark>
      <name>Eixo de Navegação ({d_metros:.0f} m)</name>
      <styleUrl>#linhaEixo</styleUrl>
      <LineString>
        <extrude>1</extrude><tessellate>1</tessellate>
        <coordinates>
          {lon_alvo},{lat_alvo},0
          {lon_pl},{lat_pl},0
        </coordinates>
      </LineString>
    </Placemark>

    <Placemark>
      <name>Ponto de Saída</name>
      <description>Altura: {A_kft:.1f} kft | Vento: {v_usado:.1f} kt</description>
      <styleUrl>#iconePonto</styleUrl>
      <Point><coordinates>{lon_pl},{lat_pl},0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""

            # Empacota no formato KMZ
            zip_buffer_dkva = io.BytesIO()
            with zipfile.ZipFile(zip_buffer_dkva, "w", zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr("planejamento_dkva.kml", kml_dkva.encode("utf-8"))
            
            kmz_bytes_dkva = zip_buffer_dkva.getvalue()
            
            st.success("KMZ do DKVA gerado com sucesso!")
            st.download_button(
                label="🗺️ Baixar KMZ do Salto (DKVA)",
                data=kmz_bytes_dkva,
                file_name="Planejamento_DKVA.kmz",
                mime="application/vnd.google-earth.kmz"
            )