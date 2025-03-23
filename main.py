import time
from instagrapi import Client
import google.generativeai as genai
from apify_client import ApifyClient
import json
from dotenv import load_dotenv
import os
import sys
from instagrapi.exceptions import ClientError, LoginRequired

load_dotenv()

# Load environment variables with fallbacks
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
APIFY_KEY = os.getenv("APIFY_KEY", "")
INSTA_USER = os.getenv("INSTA_USERNAME", "")
INSTA_PASS = os.getenv("INSTA_PASSWORD", "")

if not all([GOOGLE_API_KEY, APIFY_KEY, INSTA_USER, INSTA_PASS]):
    sys.stdout.buffer.write("Error: Missing required environment variables\n".encode('utf-8'))
    sys.stdout.buffer.flush()
    sys.exit(1)

try:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(
        'models/gemini-1.5-flash-latest',
        safety_settings={
            'HARASSMENT': 'block_none',
            'HARM_CATEGORY_HATE_SPEECH': 'block_none',
            'HARM_CATEGORY_HARASSMENT': 'block_none',
            'HARM_CATEGORY_DANGEROUS_CONTENT': 'block_none'
        }
    )
except Exception as e:
    sys.stdout.buffer.write(f"Error initializing Gemini API: {str(e)}\n".encode('utf-8'))
    sys.stdout.buffer.flush()
    sys.exit(1)

replied = {"replied_to": []}
sys.stdout.buffer.write("-----------------------------------------------\n".encode('utf-8'))
sys.stdout.buffer.write("Auto reply bot has started\n".encode('utf-8'))
sys.stdout.buffer.write("Replying to new funny reels only\n".encode('utf-8'))
sys.stdout.buffer.write("-------------------------------------------------\n".encode('utf-8'))
sys.stdout.buffer.flush()

try:
    with open('store.json', 'r') as f:
        replied = json.load(f)
except FileNotFoundError:
    sys.stdout.buffer.write("store.json not found, initializing new file\n".encode('utf-8'))
    sys.stdout.buffer.flush()
    with open('store.json', 'w') as f:
        json.dump({"replied_to": []}, f)
except json.JSONDecodeError as e:
    sys.stdout.buffer.write(f"Error decoding store.json: {str(e)}, resetting file\n".encode('utf-8'))
    sys.stdout.buffer.flush()
    with open('store.json', 'w') as f:
        json.dump({"replied_to": []}, f)
except Exception as e:
    sys.stdout.buffer.write(f"Unexpected error loading store.json: {str(e)}\n".encode('utf-8'))
    sys.stdout.buffer.flush()
    sys.exit(1)

sys.stdout.buffer.write(f"Loaded replied messages for: {INSTA_USER}\n".encode('utf-8'))
sys.stdout.buffer.flush()

cl = Client()
max_login_retries = 3
for attempt in range(max_login_retries):
    try:
        cl.login(INSTA_USER, INSTA_PASS)
        break
    except (ClientError, LoginRequired) as e:
        sys.stdout.buffer.write(f"Login failed (attempt {attempt + 1}/{max_login_retries}): {str(e)}\n".encode('utf-8'))
        sys.stdout.buffer.flush()
        if attempt < max_login_retries - 1:
            time.sleep(10)
        else:
            sys.stdout.buffer.write("Max login retries reached, exiting\n".encode('utf-8'))
            sys.stdout.buffer.flush()
            sys.exit(1)
    except Exception as e:
        sys.stdout.buffer.write(f"Unexpected login error: {str(e)}\n".encode('utf-8'))
        sys.stdout.buffer.flush()
        sys.exit(1)

def getLatestMsgs():
    max_retries = 3
    retry_delay = 10
    for attempt in range(max_retries):
        try:
            threads = cl.direct_threads()
            messages = []
            current_time = time.time()  # Current time in seconds
            time_threshold = 24 * 60 * 60  # 24 hours in seconds

            for thread in threads:
                for msg in thread.messages:
                    # Check if it's a reel, not from self, not replied to, and within last 24 hours
                    msg_timestamp = msg.timestamp.timestamp() if msg.timestamp else 0
                    if (msg.user_id != cl.user_id and 
                        msg.item_type == 'clip' and 
                        msg.id not in replied['replied_to'] and 
                        (current_time - msg_timestamp) <= time_threshold):
                        messages.append((thread, msg, msg.clip.code))
                        replied['replied_to'].append(msg.id)
                        try:
                            with open('store.json', 'w') as f:
                                json.dump(replied, f)
                        except Exception as e:
                            sys.stdout.buffer.write(f"Error writing to store.json: {str(e)}\n".encode('utf-8'))
                            sys.stdout.buffer.flush()
            return messages
        except (ClientError, LoginRequired) as e:
            sys.stdout.buffer.write(f"Error fetching threads (attempt {attempt + 1}/{max_retries}): {str(e)}\n".encode('utf-8'))
            sys.stdout.buffer.flush()
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                sys.stdout.buffer.write("Max retries reached, skipping this cycle\n".encode('utf-8'))
                sys.stdout.buffer.flush()
                return []
        except Exception as e:
            sys.stdout.buffer.write(f"Unexpected error in getLatestMsgs: {str(e)}\n".encode('utf-8'))
            sys.stdout.buffer.flush()
            return []

def getComments(reelUrl):
    try:
        client = ApifyClient(APIFY_KEY)
        run_input = {
            "directUrls": [reelUrl],
            "resultsLimit": 10,
        }
        run = client.actor("SbK00X0JYCPblD2wp").call(run_input=run_input)
        if not run or "defaultDatasetId" not in run:
            sys.stdout.buffer.write("Apify run failed or returned no dataset\n".encode('utf-8'))
            sys.stdout.buffer.flush()
            return []
        
        noOfItems = 0
        comments = []
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            if noOfItems == 5:
                break
            comment_text = item.get('text') or item.get('caption') or item.get('comment_text') or "No comment text available"
            comments.append(comment_text)
            noOfItems += 1
        return comments
    except Exception as e:
        sys.stdout.buffer.write(f"Error in getComments for {reelUrl}: {str(e)}\n".encode('utf-8'))
        sys.stdout.buffer.flush()
        return []

def generateReply(comments):
    try:
        comment_text = " ".join(comments).lower()
        funny_keywords = ["haha", "lol", "funny", "lmao", "😂", "🤣"]
        funny_count = sum(comment_text.count(keyword) for keyword in funny_keywords)

        if funny_count > 2 or "😂" in comment_text:
            prompt = (
                f"Generate a reply for a funny Instagram reel based on these comments: {comments}. "
                f"Use a playfully teasing or self-deprecating tone. Mention laughs and emojis like 😂. "
                f"Keep it concise and engaging, similar to these examples: "
                "'Thanks for the love, everyone! Guess my reel’s so good, it’s even appealing to the chronically single AND those terrified of sentient porcelain. 😂❤️', "
                "'Wow, the range of reactions! From “single and loving it” to “send help, the dolls are alive!” Thanks for the ❤️s and 😂s, you guys are wild.', "
                "'My reel: a rollercoaster of emotions! Thanks for the laughs, loves, and existential dread over creepy dolls. 😂❤️'"
            )
            chat = model.start_chat()
            response = chat.send_message(prompt)
            return response.text if response else "Nice reel!"
        else:
            return None
    except Exception as e:
        sys.stdout.buffer.write(f"Error generating reply: {str(e)}\n".encode('utf-8'))
        sys.stdout.buffer.flush()
        return None

# Run the loop every 10 seconds
while True:
    try:
        messages = getLatestMsgs()
        if not messages:
            sys.stdout.buffer.write("You have received no new reels\n".encode('utf-8'))
            sys.stdout.buffer.flush()
        else:
            for thread, msg, reel in messages:
                reel_url = 'https://www.instagram.com/p/' + reel
                comments = getComments(reel_url)
                reply = generateReply(comments)

                if reply is None:
                    continue

                if reply.startswith('"'):
                    reply = reply[1:len(reply)-1]

                sender_username = next((user.username for user in thread.users if user.pk != cl.user_id), "Unknown")

                try:
                    cl.direct_send(reply, thread_ids=[thread.id], reply_to_message=msg)
                    cl.direct_message_seen(int(thread.id), int(msg.id))
                    sys.stdout.buffer.write(f"Replied to {sender_username}: {reply}\n".encode('utf-8'))
                    sys.stdout.buffer.flush()
                except ClientError as e:
                    sys.stdout.buffer.write(f"Error sending reply to {sender_username}: {str(e)}\n".encode('utf-8'))
                    sys.stdout.buffer.flush()

        time.sleep(100)
    except Exception as e:
        sys.stdout.buffer.write(f"Unexpected error in main loop: {str(e)}\n".encode('utf-8'))
        sys.stdout.buffer.flush()
        time.sleep(10)