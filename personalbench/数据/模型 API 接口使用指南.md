模型 API 接口使用指南：

豆包

平台：火山引擎

模型部署：控制台——火山方舟——在线推理——创建推理接入点

API 管理：模型部署下拉即可显示

Openai SDK

```python
import os
from openai import OpenAI

# 从环境变量中获取您的API KEY，配置方法见：https://www.volcengine.com/docs/82379/1399008
api_key = os.getenv('ARK_API_KEY')

client = OpenAI(
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key=api_key,
)

response = client.responses.create(
    model="ep-20260207181350-dq8sf",
    input=[
        {
            "role": "user",
            "content": [

                {
                    "type": "input_image",
                    "image_url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/ark_demo_img_1.png"
                },
                {
                    "type": "input_text",
                    "text": "你看见了什么？"
                },
            ],
        }
    ]
)

print(response)
```

千问

平台：阿里云百炼

API 管理：模型服务——密钥管理

Openai SDK

```python
import os
from openai import OpenAI

# 注意: 不同地域的base_url不通用（下方示例使用北京地域的 base_url）
# - 华北2（北京）: https://dashscope.aliyuncs.com/compatible-mode/v1
# - 美国（弗吉尼亚）: https://dashscope-us.aliyuncs.com/compatible-mode/v1
# - 新加坡: https://dashscope-intl.aliyuncs.com/compatible-mode/v1
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
completion = client.chat.completions.create(
    model="qwen-plus",
    messages=[{'role': 'user', 'content': '你是谁？'}]
)
print(completion.choices[0].message.content)
```

