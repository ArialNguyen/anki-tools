import os
import sys
import pandas as pd
import json
import time
import requests
import threading
import concurrent.futures
from tqdm import tqdm
from dotenv import dotenv_values

# ==========================================
# ⚙️ SYSTEM CONFIGURATION (TÙY CHỈNH Ở ĐÂY)
# ==========================================
# Cấu hình AI
MODEL_NAME = "gemini-3-flash-preview"
CHUNK_SIZE = 20          # Số lượng từ gửi đi trong 1 request (Tối đa tốc độ)
MAX_RETRIES_AI = 30      # Số lần thử lại tối đa nếu AI trả thiếu field

# Cấu hình File Đầu vào / Đầu ra
INPUT_EXCEL_FILE = "../Vocab_mountain_Writting.xlsm"
SHEET_NAME = "Day 7"
OUTPUT_CSV_FILE = "day7_turbo_absolute.csv"

# ==========================================
# 1. API KEY MANAGER & VALIDATOR
# ==========================================
def validate_and_load_keys():
    print("🔍 Loading and verifying API Keys from .env file...\n")
    env_dict = dotenv_values(".env")
    
    all_keys = [(k, str(v).strip()) for k, v in env_dict.items() if v and str(v).strip()]
    
    if not all_keys:
        print("❌ CRITICAL ERROR: No API Keys found in .env file!")
        sys.exit(1)
        
    alive_keys = []
    dead_keys = []
    
    for idx, (var_name, key) in enumerate(all_keys, 1):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": "hi"}]}]}
        
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code in [200, 429]:
                alive_keys.append(key)
            else:
                dead_keys.append((var_name, res.status_code))
        except Exception:
            dead_keys.append((var_name, "Connection Error"))

    if dead_keys:
        print("⚠️ DEAD API KEYS DETECTED:")
        for var_name, err in dead_keys:
            print(f"   -> [{var_name}] failed | Error: {err}")
            
        if not alive_keys:
            print("\n❌ All API Keys are dead. Please update your .env file!")
            sys.exit(1)
            
        ans = input(f"\n❓ Continue with {len(alive_keys)} active keys? (yes/no): ")
        if ans.lower() not in ['y', 'yes']:
            print("👋 Exited program.")
            sys.exit(0)
    else:
        print(f"✅ Awesome! All {len(all_keys)} keys are active and ready.")
        
    print("\n" + "="*50)
    return alive_keys

API_KEYS = validate_and_load_keys()

class KeyManager:
    def __init__(self, keys):
        self.keys = keys
        self.idx = 0
        self.lock = threading.Lock()
        
    def get_next_key(self):
        with self.lock:
            key = self.keys[self.idx]
            masked_key = f"...{key[-4:]}" if len(key) > 4 else "UNKNOWN"
            self.idx = (self.idx + 1) % len(self.keys)
            return key, masked_key

key_pool = KeyManager(API_KEYS)

# ==========================================
# 2. CHECKPOINT & SAVE MANAGER
# ==========================================
file_write_lock = threading.Lock()

def load_checkpoint(output_csv):
    existing_data = {}
    if os.path.exists(output_csv):
        print(f"📂 Found existing checkpoint: '{os.path.basename(output_csv)}'. Verifying data integrity...")
        try:
            df_existing = pd.read_csv(output_csv)
            
            required_cols = ["target_word", "ipa", "vietnamese_meaning", "english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]
            for col in required_cols:
                if col not in df_existing.columns:
                    df_existing[col] = ""

            valid_count = 0
            for _, row in df_existing.iterrows():
                word = str(row.get('target_word', '')).strip().lower()
                if not word or word == 'nan': continue

                is_complete = True
                for col in ["english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]:
                    val = str(row.get(col, '')).strip()
                    if not val or val.lower() in ['nan', 'none', 'null', 'n/a', 'empty']:
                        is_complete = False
                        break

                if is_complete:
                    existing_data[word] = row.to_dict()
                    valid_count += 1
                    
            print(f"✅ Recovered {valid_count} perfectly processed words. Skipping them!\n")
        except Exception as e:
            print(f"⚠️ Failed to read checkpoint ({e}). Starting fresh.\n")
            
    return existing_data

def save_progress(current_results, output_csv):
    with file_write_lock:
        sorted_res = sorted(current_results, key=lambda x: x.get('index', 0))
        save_list = [{k: v for k, v in r.items() if k != 'index'} for r in sorted_res]
        pd.DataFrame(save_list).to_csv(output_csv, index=False, encoding='utf-8')

# ==========================================
# 3. GEMINI API CALLER & VALIDATION
# ==========================================
def call_gemini_api(prompt, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status() 
    
    data = response.json()
    raw_text = data['candidates'][0]['content']['parts'][0]['text']
    return json.loads(raw_text)

def is_valid_ai_result(res_dict):
    required_keys = ["english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]
    invalid_placeholders = ["n/a", "none", "null", "blank", "empty"]
    
    for k in required_keys:
        if k not in res_dict: return False
        val = str(res_dict[k]).strip()
        if not val or len(val) < 2 or val.lower() in invalid_placeholders:
            return False
    return True

def enrich_chunk_with_multi_keys(chunk, thread_id):
    accumulated_results = {}
    attempt = 0
    
    while len(accumulated_results) < len(chunk) and attempt < MAX_RETRIES_AI:
        attempt += 1
        missing_items = [item for item in chunk if item['word'].strip().lower() not in accumulated_results]
        
        if attempt > 1 and attempt % 3 == 0:
            tqdm.write(f"🔄 [Thread {thread_id}] Retry #{attempt} - Forcing AI to fix {len(missing_items)} incomplete words...")
            
        input_data = [{"word": item['word'], "meaning": item['meaning'], "example": item['example']} for item in missing_items]
        
        prompt = f"""
        You are a strict and expert English lexicographer. Process this JSON array:
        {json.dumps(input_data, ensure_ascii=False)}

        CRITICAL RULES (FAILURE IS NOT AN OPTION):
        1. NO EMPTY FIELDS: You MUST provide comprehensive text for EVERY field for EVERY word. 
        2. IF "example" IS EMPTY in the input, YOU MUST INVENT a meaningful example sentence.
        3. "example_front": Must be a full sentence. Replace ONLY the exact target word with "_____".
           - Right: "The waiter arrived to _____ our water glasses."
        4. "example_back": Must be the exact same sentence with the word included.
           - Right: "The waiter arrived to replenish our water glasses."
        5. DO NOT use Anki cloze format like "{{{{c1::word}}}}". Never do this.

        Respond ONLY with a JSON array of objects. Keys required exactly as follows:
        "word", "english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation".
        """
        
        current_key, masked_key = key_pool.get_next_key()
        
        try:
            results_list = call_gemini_api(prompt, current_key)
            
            for res in results_list:
                w_key = res.get("word", "").strip().lower()
                if w_key in [m['word'].strip().lower() for m in missing_items]:
                    if is_valid_ai_result(res):
                        accumulated_results[w_key] = res
                    
            if len(accumulated_results) < len(chunk):
                time.sleep(1) 
                
        except requests.exceptions.HTTPError as err:
            if err.response.status_code == 429:
                tqdm.write(f"⚠️ [Thread {thread_id}] Key ({masked_key}) Rate Limited. Rotating key...")
                time.sleep(1) 
            else:
                time.sleep(2)
        except Exception:
            time.sleep(2)

    return accumulated_results

# ==========================================
# 4. WORKER THREAD
# ==========================================
def process_chunk(chunk_idx, chunk_items, position):
    total_items = len(chunk_items)
    with tqdm(total=total_items, desc=f"Thread {chunk_idx:>2}", position=position, leave=False, 
              bar_format="{desc} |{bar}| {n_fmt}/{total_fmt} words") as pbar:
        
        ai_results_dict = enrich_chunk_with_multi_keys(chunk_items, chunk_idx)
        processed = []
        
        for item in chunk_items:
            word_key = item['word'].strip().lower()
            # Bảo vệ đề phòng AI quá lười sau MAX_RETRIES_AI
            ai_data = ai_results_dict.get(word_key, {
                'english_definition': 'N/A', 'part_of_speech': 'N/A', 
                'example_front': 'N/A', 'example_back': 'N/A', 'example_vietnamese_translation': 'N/A'
            })
            
            processed.append({
                'index': item['index'],
                'target_word': item['word'],
                'ipa': item['ipa'],
                'vietnamese_meaning': item['meaning'],
                'english_definition': ai_data['english_definition'],
                'part_of_speech': ai_data['part_of_speech'],
                'example_front': ai_data['example_front'],
                'example_back': ai_data['example_back'],
                'example_vietnamese_translation': ai_data['example_vietnamese_translation']
            })
        
        pbar.update(total_items)
    return processed

# ==========================================
# 5. MAIN PROCESSOR & AUTO-SAVE LOGIC
# ==========================================
def process_sheet(df, output_csv):
    ipa_row, ipa_col = -1, -1
    for r_idx, row in df.iterrows():
        for c_idx, val in row.items():
            if str(val).strip().lower() == 'ipa':
                ipa_row, ipa_col = r_idx, c_idx
                break
        if ipa_row != -1: break

    if ipa_row == -1: return []

    existing_data = load_checkpoint(output_csv)
    all_results = []
    items_to_process = []

    w_col, m_col, e_col = ipa_col - 1, ipa_col + 1, ipa_col + 2
    for r_idx in range(ipa_row + 1, len(df)):
        row = df.iloc[r_idx]
        word = str(row[w_col]).strip() if pd.notna(row[w_col]) else ""
        if word and word.lower() not in ['nan', 'none', '']:
            word_key = word.lower()
            
            if word_key in existing_data:
                completed_row = existing_data[word_key]
                completed_row['index'] = r_idx 
                all_results.append(completed_row)
            else:
                items_to_process.append({
                    'index': r_idx, 'word': word,
                    'ipa': str(row[ipa_col]).strip() if pd.notna(row[ipa_col]) else "",
                    'meaning': str(row[m_col]).strip() if pd.notna(row[m_col]) else "",
                    'example': str(row[e_col]).strip() if e_col < len(row) and pd.notna(row[e_col]) else ""
                })

    total_missing = len(items_to_process)
    if total_missing == 0:
        print("🎉 All words are already 100% completed in the CSV. Nothing left to do!")
        return all_results

    # Lấy thông số từ phần Config
    chunks = [items_to_process[i:i + CHUNK_SIZE] for i in range(0, total_missing, CHUNK_SIZE)]
    max_workers = len(API_KEYS) 

    print(f"🚀 STARTING TURBO MODE: {max_workers} Workers processing {total_missing} missing words...")
    print("="*50 + "\n")
    
    try:
        with tqdm(total=total_missing, desc="GLOBAL PROGRESS", position=0, leave=True, 
                  bar_format="{desc} |{bar}| {n_fmt}/{total_fmt} words [{elapsed}<{remaining}]") as pbar_global:
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for idx, chunk in enumerate(chunks):
                    futures.append(executor.submit(process_chunk, idx + 1, chunk, idx + 1))

                for future in concurrent.futures.as_completed(futures):
                    try:
                        chunk_result = future.result()
                        all_results.extend(chunk_result)
                        pbar_global.update(len(chunk_result)) 
                        
                        save_progress(all_results, output_csv)
                        
                    except Exception as exc:
                        tqdm.write(f"❌ Thread Error: {exc}")

    except KeyboardInterrupt:
        print("\n\n🛑 INTERRUPTED BY USER! The program was stopped manually.")
        print(f"💾 Don't worry, all completed chunks have been safely saved to '{os.path.basename(output_csv)}'.")
        print("Run the script again to resume from where you left off!\n")
        sys.exit(0)

    all_results.sort(key=lambda x: x['index'])
    save_progress(all_results, output_csv) 
    print("\n") 
    return all_results

# ==========================================
# 6. EXECUTION
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run_import(excel_file, sheet_name, output_csv):
    if not os.path.isabs(excel_file):
        excel_file = os.path.join(BASE_DIR, excel_file)
        if not os.path.exists(excel_file):
            excel_file = os.path.join(BASE_DIR, '..', excel_file)
    if not os.path.isabs(output_csv):
        output_csv = os.path.join(BASE_DIR, output_csv)

    try:
        df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
        data = process_sheet(df, output_csv)
        if data:
            print(f"🎉 100% COMPLETENESS ACHIEVED! Results successfully saved at '{output_csv}'.")
    except Exception as e:
        print(f"❌ System Error: {e}")

if __name__ == "__main__":
    run_import(INPUT_EXCEL_FILE, SHEET_NAME, OUTPUT_CSV_FILE)