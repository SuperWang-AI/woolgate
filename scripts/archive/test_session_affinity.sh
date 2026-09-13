#!/bin/bash
# 测试 WoolGate 会话粘性功能

TOKEN=$(grep GATEWAY_BEARER_TOKEN /Users/superwang/.openclaw/workspace/woolgate/.env | cut -d'=' -f2)
URL="http://localhost:8765/v1/chat/completions"

echo "=========================================="
echo "测试 WoolGate 会话粘性"
echo "=========================================="

# 第一轮：新对话
echo -e "\n【第一轮】新对话（无历史）"
echo "预期：选择优先级最高的账号"
RESPONSE1=$(curl -s -X POST $URL \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chat",
    "messages": [
      {"role": "user", "content": "你好，请介绍一下你自己"}
    ],
    "stream": false
  }')

CONTENT1=$(echo $RESPONSE1 | jq -r '.choices[0].message.content')
echo "回复: ${CONTENT1:0:50}..."

sleep 2

# 第二轮：多轮对话（带上第一轮的历史）
echo -e "\n【第二轮】多轮对话（带历史）"
echo "预期：继续使用第一轮的账号（会话粘性）"
RESPONSE2=$(curl -s -X POST $URL \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"chat\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"你好，请介绍一下你自己\"},
      {\"role\": \"assistant\", \"content\": \"$CONTENT1\"},
      {\"role\": \"user\", \"content\": \"1+1等于几？\"}
    ],
    \"stream\": false
  }")

CONTENT2=$(echo $RESPONSE2 | jq -r '.choices[0].message.content')
echo "回复: ${CONTENT2:0:50}..."

sleep 2

# 第三轮：继续对话
echo -e "\n【第三轮】继续对话"
echo "预期：继续使用同一账号"
RESPONSE3=$(curl -s -X POST $URL \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"chat\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"你好，请介绍一下你自己\"},
      {\"role\": \"assistant\", \"content\": \"$CONTENT1\"},
      {\"role\": \"user\", \"content\": \"1+1等于几？\"},
      {\"role\": \"assistant\", \"content\": \"$CONTENT2\"},
      {\"role\": \"user\", \"content\": \"2+2等于几？\"}
    ],
    \"stream\": false
  }")

CONTENT3=$(echo $RESPONSE3 | jq -r '.choices[0].message.content')
echo "回复: ${CONTENT3:0:50}..."

echo -e "\n=========================================="
echo "测试完成，查看日志验证会话粘性"
echo "=========================================="
