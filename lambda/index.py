# lambda/index.py
import json
import os
import urllib.request
import urllib.error

# FastAPIエンドポイントのURL (ngrokのURL)
# 必ず末尾に /generate を追加してください
FASTAPI_ENDPOINT_URL = "https://44e5-35-198-236-203.ngrok-free.app/generate" # 例: https://70fa-34-123-186-226.ngrok-free.app/generate

def lambda_handler(event, context):
    try:
        print("Received event:", json.dumps(event))

        user_info = None
        if 'requestContext' in event and 'authorizer' in event['requestContext']:
            user_info = event['requestContext']['authorizer']['claims']
            print(f"Authenticated user: {user_info.get('email') or user_info.get('cognito:username')}")

        body = json.loads(event['body'])
        user_message_content = body['message']
        conversation_history_input = body.get('conversationHistory', [])

        print("Processing user message:", user_message_content)
        print("Current conversation history:", json.dumps(conversation_history_input))

        # FastAPIに送信するペイロードを作成
        # app.py の /generate エンドポイントは 'prompt' を期待
        fastapi_payload = {
            "prompt": user_message_content,
            # 必要に応じて、app.pyのSimpleGenerationRequestで定義されている他のパラメータも追加可能
            # "max_new_tokens": 512,
            # "temperature": 0.7,
        }

        print(f"Calling FastAPI at {FASTAPI_ENDPOINT_URL} with payload:", json.dumps(fastapi_payload))

        req = urllib.request.Request(
            FASTAPI_ENDPOINT_URL,
            data=json.dumps(fastapi_payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            method='POST' # /generate エンドポイントは POST
        )

        assistant_response_text = ""

        with urllib.request.urlopen(req) as response:
            response_status = response.getcode()
            response_data = response.read()
            print(f"FastAPI response status: {response_status}")

            if not response_data:
                print("FastAPI returned an empty response.")
                raise Exception("FastAPI returned an empty response.")

            fastapi_response_body = json.loads(response_data.decode('utf-8'))
            print("FastAPI response body:", json.dumps(fastapi_response_body, default=str))

            # FastAPIからのレスポンスを解析 (app.pyのGenerationResponse形式)
            if 'generated_text' in fastapi_response_body:
                assistant_response_text = fastapi_response_body['generated_text']
            else:
                error_message = "FastAPI response is missing 'generated_text' key."
                print(f"Error: {error_message} Received body: {fastapi_response_body}")
                raise Exception(error_message)

        # 更新された会話履歴を作成
        updated_conversation_history = conversation_history_input.copy()
        updated_conversation_history.append({"role": "user", "content": user_message_content})
        updated_conversation_history.append({"role": "assistant", "content": assistant_response_text})

        print("Generated assistant response:", assistant_response_text)
        print("Updated conversation history:", json.dumps(updated_conversation_history))

        # 成功レスポンスの返却
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": True,
                "response": assistant_response_text,
                "conversationHistory": updated_conversation_history
            })
        }

    except urllib.error.HTTPError as e:
        error_body_text = "N/A"
        try:
            error_body_text = e.read().decode('utf-8', errors='replace')
        except Exception as read_err:
            print(f"Could not read HTTPError body: {read_err}")
        print(f"HTTPError calling FastAPI: Status {e.code}, Reason {e.reason}. Body: {error_body_text}", exc_info=True)
        return {
            "statusCode": e.code,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": f"FastAPI Error: {e.code} {e.reason}",
                "details": error_body_text
            })
        }
    except urllib.error.URLError as e:
        print(f"URLError calling FastAPI: {e.reason}", exc_info=True)
        return {
            "statusCode": 503,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": f"FastAPI Connection Error: {e.reason}"
            })
        }
    except json.JSONDecodeError as e:
        print(f"JSONDecodeError: {str(e)}. FastAPI response might not be valid JSON.", exc_info=True)
        return {
            "statusCode": 502,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": f"Failed to decode FastAPI JSON response: {str(e)}"
            })
        }
    except Exception as error:
        print(f"Lambda handler generic error: {str(error)}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": str(error)
            })
        }