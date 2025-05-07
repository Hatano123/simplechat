# lambda/index.py
import json
import os
import urllib.request
import urllib.error
import traceback # エラー時のスタックトレース表示用

# 呼び出す外部URL (環境変数 NGROK_URL が設定されていればそれを使用、なければデフォルト値)
NGROK_URL = os.environ.get("NGROK_URL", "https://70fa-34-123-186-226.ngrok-free.app")
# 外部URL呼び出しのタイムアウト（秒）(環境変数 URL_TIMEOUT が設定されていればそれを使用、なければデフォルト値)
URL_TIMEOUT = int(os.environ.get("URL_TIMEOUT", "15"))

def lambda_handler(event, context):
    try:
        print("Received event:", json.dumps(event))
        
        # Cognitoで認証されたユーザー情報を取得 (オプション)
        user_info = None
        if ('requestContext' in event and 
            'authorizer' in event['requestContext'] and 
            event['requestContext']['authorizer'] and # authorizerがNoneでないことを確認
            'claims' in event['requestContext']['authorizer']):
            user_info = event['requestContext']['authorizer']['claims']
            print(f"Authenticated user: {user_info.get('email') or user_info.get('cognito:username')}")
        
        # リクエストボディの解析
        body = json.loads(event['body'])
        message_text = body['message']  # ユーザーの現在の入力テキスト
        conversation_history = body.get('conversationHistory', [])  # これまでの会話のリスト [{role, content}, ...]
        
        print("Processing message:", message_text)
        
        # 外部URLに送信するためのメッセージリストを作成
        # (過去の履歴 + 今回のユーザー発言)
        messages_for_external_service = conversation_history.copy()
        messages_for_external_service.append({
            "role": "user",
            "content": message_text
        })
        
        # 外部URLに送信するペイロード
        payload_to_ngrok = {
            "messages": messages_for_external_service,
        }
        # ユーザー情報が存在し、外部サービスがそれを必要とする場合はペイロードに追加
        if user_info:
            payload_to_ngrok["userInfo"] = {
                "email": user_info.get('email'),
                "username": user_info.get('cognito:username'),
                "sub": user_info.get('sub') # CognitoユーザーID
            }
            
        print(f"Calling external URL: {NGROK_URL} with payload:", json.dumps(payload_to_ngrok))
        
        req_data = json.dumps(payload_to_ngrok).encode('utf-8')
        
        headers = {
            'Content-Type': 'application/json',
            # 外部APIがAPIキーを必要とする場合は、環境変数などから取得してヘッダーに追加
            # 'Authorization': f'Bearer {os.environ.get("EXTERNAL_API_KEY")}'
        }
        
        req = urllib.request.Request(NGROK_URL, data=req_data, headers=headers, method='POST')
        
        assistant_response_content = ""
        external_response_body_str = "" # エラーログ用に保持
        
        try:
            with urllib.request.urlopen(req, timeout=URL_TIMEOUT) as http_response:
                response_body_bytes = http_response.read()
                external_response_body_str = response_body_bytes.decode('utf-8')
                print(f"External URL response status: {http_response.status}")
                print(f"External URL response body: {external_response_body_str}")
                
                if 200 <= http_response.status < 300:
                    ngrok_response_data = json.loads(external_response_body_str)
                    # 外部URLのレスポンス形式を仮定: {"response": "AIのテキスト"}
                    if 'response' in ngrok_response_data and isinstance(ngrok_response_data['response'], str):
                        assistant_response_content = ngrok_response_data['response']
                    else:
                        # レスポンスの 'response' フィールドが期待通りでない場合
                        error_msg = "External service response is valid JSON but does not contain a 'response' string field."
                        print(f"Warning: {error_msg} Received: {json.dumps(ngrok_response_data)}")
                        raise Exception(f"Invalid response structure from external service: {error_msg}")
                else:
                    # HTTPステータスコードが2xx以外の場合
                    error_message = f"External URL request failed with status {http_response.status}: {external_response_body_str}"
                    print(error_message)
                    raise Exception(error_message)

        except urllib.error.HTTPError as e:
            # HTTPエラーの場合、e.read()でレスポンスボディが読めることがある
            error_body_content = "No additional error content"
            try:
                if e.fp: # e.fp is the file-like object for the error response body
                    error_body_content = e.fp.read().decode('utf-8')
            except Exception as read_err:
                print(f"Could not read HTTPError response body: {read_err}")
            error_message = f"HTTPError when calling external URL: {e.code} {e.reason}. Response: {error_body_content}"
            print(error_message)
            raise Exception(error_message)
        except urllib.error.URLError as e:
            # ネットワーク接続エラー、タイムアウトなど
            error_message = f"URLError when calling external URL: {e.reason}"
            print(error_message)
            raise Exception(error_message)
        except json.JSONDecodeError as e:
            # 外部サービスの応答がJSON形式でない場合
            error_message = f"JSONDecodeError parsing external URL response: {e}. Response was: {external_response_body_str}"
            print(error_message)
            raise Exception(error_message)
        
        if not assistant_response_content:
            # この条件は、通常上記のtry-exceptブロック内で処理されるはず。
            # ここに到達した場合、何らかの予期せぬケース。
            print("Critical: Assistant response content is empty after external URL call without a prior specific exception.")
            raise Exception("Failed to get a valid response from the external service.")

        # アシスタントの応答を会話履歴に追加
        # messages_for_external_service はユーザーの今回の発言までを含んでいる
        final_conversation_history = messages_for_external_service.copy()
        final_conversation_history.append({
            "role": "assistant",
            "content": assistant_response_content
        })
        
        # 成功レスポンスの返却
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*", # 本番環境ではより具体的に指定することを推奨
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": True,
                "response": assistant_response_content,
                "conversationHistory": final_conversation_history # 更新された全会話履歴
            })
        }
        
    except Exception as error:
        print(f"Error in lambda_handler: {str(error)}")
        # スタックトレースをCloudWatch Logsに出力するとデバッグに役立ちます
        print(traceback.format_exc())
        
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*", # エラー時もCORSヘッダーは重要
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": str(error) # クライアントにはエラーの概要のみを返すのが一般的
            })
        }