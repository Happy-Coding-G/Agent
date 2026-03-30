##### 模型

使用 langchain_openai 调用 Deepseek API 接口

```
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model='deepseek-chat',
    openai_api_key='sk-4fbe9136ca3846dcbc3b88cc932cf1a8',
    openai_api_base='https://api.deepseek.com/v1',
    temperature=0.3
)

response = model.invoke("请回答我理财有哪些分类？")
print(response)
```

invoke 函数  （返回AIMeaasge对象）

```
# 传入单个消息或列表
response = model.invoke("为什么鹦鹉有五颜六色的羽毛？")
print(response)
```

```
# 传入消息列表，表示对话历史
from langchain_core.meaasges import HumanMessage, AIMessage, SystemMessage

conversation = [
    SystemMessage(content="你是一个将英语翻译成法语的有用助手。"),
    HumanMessage(content="翻译：我喜欢编程。"),
    AIMessage(content="J'adore la programmation."),
    HumanMessage(content="翻译：我喜欢构建应用程序。")
]

response = model.invoke(conversation)
print(response.content)
```

stream 函数（返回多个AIMessageChunk对象）

```
# 流式输出，stream函数返回迭代器
for chunk in model.stream("为什么鹦鹉有五颜六色的羽毛？"):
    print(chunk.text, end="|", flush=True)
```

 [`astream_events()`](https://reference.langchain.com/python/langchain_core/language_models/#langchain_core.language_models.chat_models.BaseChatModel.astream_events) 流式传输语义事件

```
async for event in model.astream_events("你好"):

    if event["event"] == "on_chat_model_start":
        print(f"输入：{event['data']['input']}")

    elif event["event"] == "on_chat_model_stream":
        print(f"令牌：{event['data']['chunk'].text}")

    elif event["event"] == "on_chat_model_end":
        print(f"完整消息：{event['data']['output'].text}")

    else:
        pass
```

batch 函数

```
responses = model.batch([
    "为什么鹦鹉有五颜六色的羽毛？",
    "飞机是如何飞行的？",
    "什么是量子计算？"
])
for response in responses:
    print(response)
```

batch 函数仅返回最终输出，使用 batch_as_completed 函数进行流式输出

```
for response in model.batch_as_completed([
    "为什么鹦鹉有五颜六色的羽毛？",
    "飞机是如何飞行的？",
    "什么是量子计算？"
]):
    print(response)
```

工具调用

```
from langchain_openai import ChatOpenAI
from langchain.tools import tool

model = ChatOpenAI(
    model='deepseek-chat',
    openai_api_key='sk-4fbe9136ca3846dcbc3b88cc932cf1a8',
    openai_api_base='https://api.deepseek.com/v1',
    temperature=0.3
)

@tool
def get_weather(location: str) -> str:
    """获取某个位置的天气。"""
    return f"{location} good"

model_with_tools = model.bind_tools([get_weather])

response = model_with_tools.invoke("波士顿的天气怎么样？")

for tool_call in response.tool_calls:
    print(f"工具：{tool_call['name']}")
    print(f"参数：{tool_call['args']}")
```

工具执行循环

```
# 将（可能多个）工具绑定到模型
model_with_tools = model.bind_tools([get_weather])

# 步骤 1：模型生成工具调用
messages = [{"role": "user", "content": "波士顿的天气怎么样？"}]
ai_msg = model_with_tools.invoke(messages)
messages.append(ai_msg)

# 步骤 2：执行工具并收集结果
for tool_call in ai_msg.tool_calls:
    # 使用生成的参数执行工具
    tool_result = get_weather.invoke(tool_call)
    messages.append(tool_result)

# 步骤 3：将结果传递回模型以获取最终响应
final_response = model_with_tools.invoke(messages)
print(final_response.text)
# "波士顿当前天气为 72°F，晴朗。"
```

速率限制

```
from langchain_openai import ChatOpenAI
from langchain_core.rate_limiters import InMemoryRateLimiter

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.1,  # 每 10 秒 1 个请求
    check_every_n_seconds=0.1,  # 每 100 毫秒检查是否允许发出请求
    max_bucket_size=10,  # 控制最大突发大小。
)

model = ChatOpenAI(
    model='deepseek-chat',
    openai_api_key='sk-4fbe9136ca3846dcbc3b88cc932cf1a8',
    openai_api_base='https://api.deepseek.com/v1',
    temperature=0.3,
    rate_limiter=rate_limiter
)

response = model.invoke("今天有什么新闻？")
print(response.content_blocks)
```

文本提示

```
response = model.invoke("Write a haiku about spring")
```

消息提示

```
from langchain.messages import SystemMessage, HumanMessage, AIMessage

messages = [
    SystemMessage("You are a poetry expert"),
    HumanMessage("Write a haiku about spring"),
    AIMessage("Cherry blossoms bloom...")
]
response = model.invoke(messages)
```

字典格式

```
messages = [
    {"role": "system", "content": "You are a poetry expert"},
    {"role": "user", "content": "Write a haiku about spring"},
    {"role": "assistant", "content": "Cherry blossoms bloom..."}
]
response = model.invoke(messages)
```

系统消息

```
SystemMessage 表示一组初始指令，用于引导模型的行为
```

人类消息

```
HumanMessage 表示用户输入和交互
```

AI 消息

```
AIMessage 表示模型调用的输出，包含响应中的所有关联元数据
工具调用信息：tool_calls
令牌计数：usage_metadata
```

