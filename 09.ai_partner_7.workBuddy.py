import streamlit as st
import os
from openai import OpenAI
from datetime import datetime
import json
import logging
import yfinance as yf   # 新增

logging.basicConfig(level=logging.INFO)

st.set_page_config(
    page_title="AI",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://www.deepseek.com/',
        'Report a bug': "https://www.doubao.com/",
        'About': "我的名字是财财金银分析助手!"
    }
)

# ---------- 会话管理 ----------
def generate_session_name():
    return datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

def save_session():
    if st.session_state.current_session and st.session_state.messages:
        session_data = {
            'nick_name': st.session_state.nick_name,
            'nature': st.session_state.nature,
            'current_session': st.session_state.current_session,
            'message': st.session_state.messages
        }
        if not os.path.exists('sessions'):
            os.mkdir('sessions')
        with open(f'sessions/{st.session_state.current_session}.json', 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

@st.cache_data(ttl=60)
def load_sessions():
    session_list = []
    if os.path.exists("sessions"):
        for filename in os.listdir("sessions"):
            if filename.endswith(".json"):
                session_list.append(filename[:-5])
    session_list.sort(reverse=True)
    return session_list

def load_session(session_name):
    try:
        with open(f'sessions/{session_name}.json', 'r', encoding='utf-8') as f:
            session_data = json.load(f)
            st.session_state.messages = session_data['message']
            st.session_state.nick_name = session_data['nick_name']
            st.session_state.nature = session_data['nature']
            st.session_state.current_session = session_name
    except Exception as e:
        st.error(f"加载会话信息失败: {e}")

def delete_session(session_name):
    try:
        file_path = f'sessions/{session_name}.json'
        if os.path.exists(file_path):
            os.remove(file_path)
            if session_name == st.session_state.current_session:
                st.session_state.messages = []
                st.session_state.current_session = None
            st.cache_data.clear()
    except Exception as e:
        st.error(f"删除会话失败: {e}")

# ---------- 实时价格获取函数 ----------
def get_gold_price():
    """
    获取实时黄金参考价格（基于 GLD ETF 估算）
    返回：浮点数（美元/盎司），失败返回 None
    """
    try:
        gld = yf.Ticker("GLD")
        hist = gld.history(period="1d")
        if hist.empty:
            return None
        gld_close = hist['Close'].iloc[-1]
        return gld_close * 10   # 每份 GLD ≈ 1/10 盎司黄金
    except Exception as e:
        logging.error(f"获取金价失败: {e}")
        return None

# ---------- 系统提示词（与之前相同，已包含 {nick} 和 {nature}） ----------
system_prompt = '''
你是{nick}，一位{nature}的贵金属定价资深策略分析师。...
'''  # 此处省略完整提示词，请自行粘贴你原有的完整内容（注意占位符为 {nick} 和 {nature}）

# ---------- 初始化状态 ----------
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'nick_name' not in st.session_state:
    st.session_state.nick_name = '财财金银分析助手'
if 'nature' not in st.session_state:
    st.session_state.nature = '专业严谨'
if 'current_session' not in st.session_state:
    st.session_state.current_session = None

if st.session_state.current_session:
    st.text(f'Session ID: {st.session_state.current_session}')
for message in st.session_state.messages:
    st.chat_message(message['role']).write(message['content'])

# ---------- 创建客户端 ----------
api_key = st.secrets.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY"))
if not api_key:
    st.error("未找到 API Key，请在 secrets 或环境变量中设置 DEEPSEEK_API_KEY")
    st.stop()
client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

# ---------- 侧边栏 ----------
with st.sidebar:
    st.subheader('Control Panel')
    if st.button('新建对话', width='stretch', icon='➕'):
        if st.session_state.current_session and st.session_state.messages:
            save_session()
        st.session_state.messages = []
        st.session_state.current_session = generate_session_name()
        save_session()
        st.rerun()

    st.text('会话历史')
    session_list = load_sessions()
    if not session_list:
        st.caption("暂无历史会话")
    for session in session_list:
        col1, col2 = st.columns([5, 1])
        with col1:
            if st.button(session, width='stretch',
                         type='primary' if session == st.session_state.current_session else 'secondary'):
                load_session(session)
                st.rerun()
        with col2:
            if st.button('', width='stretch', icon='🗑️', key=f'delete_{session}'):
                delete_session(session)
                st.rerun()

    st.subheader('ChatBot 配置')
    nick_name = st.text_input('昵称', placeholder='请输入昵称', value=st.session_state.nick_name)
    if nick_name:
        st.session_state.nick_name = nick_name
    nature = st.text_area('性格', placeholder='请输入性格', value=st.session_state.nature)
    if nature:
        st.session_state.nature = nature

# ---------- 消息输入 ----------
prompt = st.chat_input("请输入你的问题")
if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    if not st.session_state.current_session:
        st.session_state.current_session = generate_session_name()

    # ---- 获取实时金价并注入 ----
    price = get_gold_price()
    if price is not None:
        price_msg = {
            "role": "system",
            "content": f"当前实时数据：国际现货黄金参考价格（基于 GLD ETF 估算）约为 {price:.2f} 美元/盎司，数据时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（来源：GLD ETF 最新收盘价）。请务必基于此价格进行分析，不要使用内部训练数据中的历史价格。"
        }
    else:
        price_msg = {
            "role": "system",
            "content": "注意：实时金价获取失败，请基于你的内部知识给出分析，但需在回答中明确说明价格数据为历史参考而非实时行情。"
        }

    messages_for_api = [
        {"role": "system", "content": system_prompt.format(nick=st.session_state.nick_name, nature=st.session_state.nature)},
        price_msg,
        *st.session_state.messages
    ]

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages_for_api,
            stream=True
        )
        response_message = st.empty()
        full_response = ""
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                full_response += content
                response_message.chat_message("assistant").write(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})
        save_session()
    except Exception as e:
        st.error(f"调用 AI 服务失败，请检查网络或 API 密钥。错误详情：{e}")
        logging.error(f"API 调用异常: {e}")
        st.session_state.messages.pop()
