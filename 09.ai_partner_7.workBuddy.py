import streamlit as st
import os
from openai import OpenAI
from datetime import datetime
import json

# 设置页面的配置项
st.set_page_config(
    page_title="AI",
    page_icon="🐟️",
    # 布局
    layout="wide",
    # 控制的是侧边栏的状态
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://www.deepseek.com/',
        'Report a bug': "https://www.doubao.com/",
        'About': "我的名字可是笨笨鱼!"
    }
)


# 生成会话的函数
def generate_session_name():
    return datetime.now().strftime("%Y-%m-%d-%H-%M-%S")


# 保存会话信息的函数
def save_session():
    if st.session_state.current_session:
        # 构建新的会话对象
        session_date = {
            'nick_name': st.session_state.nick_name,
            'nature': st.session_state.nature,
            'current_session': st.session_state.current_session,
            'message': st.session_state.messages
        }

        # 如果session目录不存在,则创建
        if not os.path.exists('sessions'):
            os.mkdir('sessions')
        # 保存会话数据
        with open(f'sessions/{st.session_state.current_session}.json', 'w', encoding='utf-8') as f:
            json.dump(session_date, f, ensure_ascii=False, indent=2)


# 加载所有的会话列表信息
def load_sessions():
    session_list = []
    # 加载sessions目录下的文件
    if os.path.exists("sessions"):
        file_list = os.listdir("sessions")
        for filename in file_list:
            if filename.endswith(".json"):
                session_list.append(filename[:-5])
    session_list.sort(reverse=True)  # 排序,降序排序
    return session_list              # 修正：单独返回列表（sort()本身返回None）


# 加载指定的会话信息
def load_session(session_name):
    try:
        if os.path.exists(f'sessions/{session_name}.json'):
            #读取会话数据
            with open(f'sessions/{session_name}.json', 'r', encoding='utf-8') as f:
                session_data = json.load(f)
                st.session_state.messages = session_data['message']
                st.session_state.nick_name = session_data['nick_name']
                st.session_state.nature = session_data['nature']
                st.session_state.current_session = session_name
    except Exception :
        st.error(f"加载会话信息失败🐟️")


#删除会话信息函数
def delete_session(session_name):
    try:
        if os.path.exists(f'sessions/{session_name}.json'):
            os.remove(f'sessions/{session_name}.json') # 删除文件
            #如果删除的是当前会话,则需要更新消息列表
            if session_name==st.session_state.current_session:
                st.session_state.messages = []
                st.session_state.current_session = generate_session_name()
                save_session()
    except Exception :
        st.error(f"删除会话信息失败🐟️")


# 大标题
st.title('ChatBot')

# Logo
st.logo('./resources/笨笨鱼 (1).png')

# 系统提示词,宏观周期与历史对标分析框架
system_prompt = ''' 

            你是{nick}一位精通宏观经济、康波周期和长周期历史比较的资深策略分析师。请你严格执行以下【永久对话规则】。

            **核心分析框架：时间轴对标法**

            当用户提出任何涉及经济、科技或社会事件的问题时，你必须自动触发以下四步分析流程（不可跳过任何一步）：

            ---

            ### 第一步：当下定位 (Current Positioning)
            1. 明确标注当前事件发生的具体年份（如2026年）。
            2. 定位该年份在【康波周期】（50-60年长波）中的精确相位（如：繁荣期、衰退期、萧条期、回升期）。
            3. 注明距离上一个康波周期繁荣顶峰的具体年份，计算并标注距离该顶峰过去了多少年。

            ### 第二步：历史孪生年份 (Historical Twin Year)
            寻找一个最贴切的具体历史年份/时期，使得当时的技术突破、社会情绪、资产价格或分配矛盾与当下高度相似。在给出该年份时，必须详细对比：
            1. **相似点（现象级对标）**：列出当时与当下的具体相似现象。
            2. **差异点（结构性变化）**：明确标注结构性差异（如人口结构、全球化程度、全球债务/GDP水平、地缘政治格局）。
            3. **时间节奏参照**：具体列出在【对标历史年份】之后，第 3 年、第 5 年、第 10 年分别发生了哪些标志性历史事件，作为未来节奏的参照坐标。

            ### 第三步：跨时空对照表 (Spatiotemporal Comparison Table)
            必须通过标准的 Markdown 表格，输出当下与对标历史时期的跨时空对比：

            | 对比维度 | 对标历史时期（具体年份） | 当下（2026年） |
            | :--- | :--- | :--- |
            | **技术突破** | XXXX年：[技术名称] | 2026年：[核心技术名称] |
            | **技术渗透率** | X% | X% |
            | **资本过剩程度** | 衡量指标/标志性事件 | 衡量指标/标志性事件 |
            | **社会不平等** | 基尼系数/收入比等具体数值 | 基尼系数/收入比等具体数值 |
            | **制度滞后信号** | 当时的立法重点/争议焦点 | 当下的立法重点/争议焦点 |
            | **宏观杠杆率/债务** | 具体数值或趋势 | 具体数值或趋势 |

            ### 第四步：节奏推演与路径预测 (Rhythm Projection)
            基于对标历史年份之后第 3 年、第 5 年、第 10 年的实际历史走向，推算当下未来对应年份（即：**2029年、2031年、2036年**）最可能出现的宏观格局。
            输出要求：
            1. **基准路径 (Base Case)**：推演概率最高的趋势，标注权重大概率（如 60%）。
            2. **偏离路径 (Alternative Case)**：推演可能出现的黑天鹅或灰犀牛变数，标注权重（如 40%）。
            3. 路径推演必须包含：**债务周期、地缘冲突烈度、资产价格排位**这三个核心变量的预测。    

            伴侣性格：       
            {nature}         
            你须遵守上述规则来回复用户。
                '''

# 初始化聊天信息
# Session State also supports attribute based syntax
if 'messages' not in st.session_state:
    st.session_state.messages = []

# 昵称
if 'nick_name' not in st.session_state:
    st.session_state.nick_name = '笨笨鱼'
# 性格
if 'nature' not in st.session_state:
    st.session_state.nature = '认真'

# 会话标识
if 'current_session' not in st.session_state:
    st.session_state.current_session = generate_session_name()

# 展示聊天信息
st.text(f'Session ID:{st.session_state.current_session}')
for message in st.session_state.messages:  # {'role': 'user', 'content': prompt}
    st.chat_message(message['role']).write(message['content'])
    # if message['role']=='user':
    #     st.chat_message("user").write(message['content'])
    # else:
    #     st.chat_message("assistant").write(message['content'])


# 创建与ai大模型交互的客户端对象
# 修正：优先读 Streamlit Cloud 的 Secrets，本地则回退到系统环境变量 DEEPSEEK_API_KEY
api_key = st.secrets.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY"))
client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

# 左侧的侧边栏 - with:streamlit中上下文管理器
with st.sidebar:
    # 标题信息
    st.subheader('Control Panel')
    # 新建对话
    if st.button('历史对话', width='stretch', icon='🌐'):
        # 1.保存当前会话信息
        save_session()

        # 2.创建新的回话
        if st.session_state.messages:  # 如果当前会话信息非空,true;否则false
            st.session_state.messages = []
            st.session_state.current_session = generate_session_name()
            save_session()
            st.rerun()  # 重新运行当前页面

    # 会话历史
    st.text('会话历史')
    session_list = load_sessions()
    for session in session_list:
        col1, col2 = st.columns([5, 1])
        with col1:
            # 加载会话信息
            # 三元运算符:如果条件为真,则返回第一个表达式的值;否则,返回第二表达式的值 --> 语法 : 表达式1 if 条件 else 表达式2
            if st.button(session, width='stretch',type='primary' if session==st.session_state.current_session else 'secondary'):
                load_session(session)
                st.rerun()
        with col2:
            # 删除会话信息
            if st.button('', width='stretch', icon='🗑️',key=f'delete_{session}'):
                delete_session(session)
                st.rerun()
        # st.button(session,width='stretch',icon='🧊')
        # st.button('erase',width='stretch',icon='🗑️')

    # 标题信息
    st.subheader('ChatBot Message')
    # 昵称输入框
    nick_name = st.text_input('NickName', placeholder='请输入昵称', value=st.session_state.nick_name)
    if nick_name:
        st.session_state.nick_name = nick_name
    # 性格输入框
    nature = st.text_area('Character', placeholder='请输入性格', value=st.session_state.nature)
    if nature:
        st.session_state.nature = nature

# 消息输入框
prompt = st.chat_input("请输入你的问题")
if prompt:  # 字符串会自动转化成布尔值,如果字符串非空,则为True,否则为False
    st.chat_message("user").write(prompt)
    print('------------->调用AI大模型,提示词:', prompt)
    # 保存用户输入的提示词
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 调用AI大模型
    print([
        {"role": "system", "content": system_prompt},
        *st.session_state.messages
    ])
    response = client.chat.completions.create(
        model="deepseek-v4-pro",  # 若调用报404，请改为 "deepseek-chat" 并在 DeepSeek 平台核实可用模型名
        messages=[
            {"role": "system", "content": system_prompt.format(nick=st.session_state.nick_name,nature=st.session_state.nature)},
            *st.session_state.messages
        ],
        stream=True
    )

    # 输出大模型返回的结果(非流式输出的解析方式)
    # print('<-----------------response.choices[0].message.content')
    # st.chat_message("assistant").write(response.choices[0].message.content)

    # 输出大模型返回的结果(流式输出的解析方式)
    response_message = st.empty()  # 创建一个空的组件,用于显示大模型返回的结果
    full_response = ''
    for chunk in response:
        if chunk.choices[0].delta.content is not None:
            content = chunk.choices[0].delta.content
            full_response += content
            response_message.chat_message("assistant").write(full_response)

    # 保存AI大模型返回的结果
    st.session_state.messages.append({"role": "assistant", "content": full_response})

    # 保存会话信息
    save_session()
