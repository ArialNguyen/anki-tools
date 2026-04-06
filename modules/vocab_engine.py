from .terminal_ui import DashboardUI
from .api_manager import KeyManager

import os
import sys
import json
import time
import requests
import threading
import concurrent.futures

import pandas as pd
from dotenv import dotenv_values

from rich.live import Live
from rich.console import Console

# Khởi tạo đối tượng in log màu toàn cục
console = Console()


class VocabEnricher:
    def __init__(self, env_path=".env", config=None):
        # Lấy cấu hình mặc định nếu người dùng không truyền vào
        if not config:
            raise ValueError("❌ CRITICAL ERROR: Class VocabEnricher bắt buộc phải nhận dictionary config để khởi chạy!")
        
        self.config = config
        if config:
            self.config.update(config)

        self.api_keys = self._load_keys(env_path)
        self.num_workers = len(self.api_keys)
        
        # Thiết lập đường dẫn lưu file
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.export_dir = os.path.join(self.base_dir, self.config["OUTPUT_DIR"])
        os.makedirs(self.export_dir, exist_ok=True)
        
        # Các khóa Lock để chống đụng độ giữa các luồng (Thread-safe)
        self.file_write_lock = threading.Lock()
        self.worker_lock = threading.Lock()
        self.failed_words_lock = threading.Lock()
        
        self.failed_words = []
        self.available_workers = list(range(self.num_workers))
        
        # Khởi tạo Quản đốc Key và Giao diện UI
        self.key_manager = KeyManager(self.api_keys, self.base_dir, self.config)
        self.ui = DashboardUI(self.num_workers)

    def _load_keys(self, env_path):
        env_dict = dotenv_values(env_path)
        keys = [(k, str(v).strip()) for k, v in env_dict.items() if v and str(v).strip()]
        if not keys:
            console.print("❌ [bold red]CRITICAL ERROR: No API Keys found in .env file![/]")
            sys.exit(1)
            
        console.print(f"✅ [bold green]Loaded {len(keys)} API keys.[/]")
        
        # --- ĐÃ TRẢ LẠI CÂU HỎI YES/NO CỦA BẠN ---
        ans = console.input(f"\n❓ [bold cyan]Continue with {len(keys)} active keys? (yes/no): [/]")
        if ans.lower() not in ['y', 'yes']:
            console.print("👋 Exited program.")
            sys.exit(0)
            
        return keys
    
    
    def _load_checkpoint(self, output_csv):
        existing_data = {}
        if os.path.exists(output_csv):
            try:
                df_existing = pd.read_csv(output_csv)
                required_cols = ["target_word", "ipa", "vietnamese_meaning", "english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]
                for col in required_cols:
                    if col not in df_existing.columns: df_existing[col] = ""

                valid_count = 0
                for _, row in df_existing.iterrows():
                    word = str(row.get('target_word', '')).strip().lower()
                    if not word or word == 'nan': continue
                    is_complete = all(str(row.get(c, '')).strip() and str(row.get(c, '')).strip().lower() not in ['nan', 'none', 'null', 'n/a', 'empty'] for c in required_cols[3:])
                    if is_complete:
                        existing_data[word] = row.to_dict()
                        valid_count += 1
                console.print(f"📂 Recovered {valid_count} processed words from checkpoint.\n")
            except Exception as e:
                console.print(f"⚠️ [bold yellow]Failed to read checkpoint ({e}). Starting fresh.[/]\n")
        return existing_data

    def _save_progress(self, current_results, output_csv):
        with self.file_write_lock:
            sorted_res = sorted(current_results, key=lambda x: x.get('index', 0))
            save_list = [{k: v for k, v in r.items() if k != 'index'} for r in sorted_res]
            pd.DataFrame(save_list).to_csv(output_csv, index=False, encoding='utf-8')

    def _call_api_raw(self, prompt, api_key, model_name):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {}}
        
        if "gemini" in model_name.lower(): 
            payload["generationConfig"]["responseMimeType"] = "application/json"
            
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        res.raise_for_status() 
        
        data = res.json()
        try:
            candidates = data.get('candidates', [])
            if not candidates: raise ValueError("No candidates.")
            texts = [part.get('text', '') for part in candidates[0].get('content', {}).get('parts', [])]
            raw_text = "".join(texts)
        except Exception as e:
            raise ValueError(f"JSON structure err: {e}")

        tokens = data.get('usageMetadata', {}).get('totalTokenCount', 1000)
        return raw_text.strip(), tokens

    def _is_valid_result(self, res_dict):
        req_keys = ["english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]
        invalid = ["n/a", "none", "null", "blank", "empty"]
        for k in req_keys:
            if k not in res_dict: return False
            val = str(res_dict[k]).strip()
            if not val or len(val) < 2 or val.lower() in invalid: return False
        return True
    
    def _enrich_chunk_with_multi_keys(self, chunk, task_id):
        acc_results, attempt, max_retries = {}, 0, self.config["MAX_RETRIES_AI"]
        
        while len(acc_results) < len(chunk) and attempt < max_retries:
            attempt += 1
            missing = [i for i in chunk if i['word'].strip().lower() not in acc_results]
            
            if attempt > 1: 
                self.ui.thread_progress.update(task_id, status=f"[yellow]Retry #{attempt} (Fixing {len(missing)})[/]")
                
            input_data = [{"word": i['word'], "meaning": i['meaning'], "example": i['example']} for i in missing]
            
            # ĐÃ TRẢ LẠI NGUYÊN VĂN PROMPT CŨ CỦA BẠN (GIỮ ĐỘ STRICT 100%)
            prompt = f"""
            You are a strict and expert English lexicographer. Process this JSON array:
            {json.dumps(input_data, ensure_ascii=False)}

            CRITICAL RULES (FAILURE IS NOT AN OPTION):
            1. NO EMPTY FIELDS: You MUST provide comprehensive text for EVERY field for EVERY word. 
            2. IF "example" IS EMPTY in the input, YOU MUST INVENT a meaningful example sentence.
            3. "example_front": Must be a full sentence. Replace ONLY the exact target word with "_____".
            4. "example_back": Must be the exact same sentence with the word included.
            5. DO NOT use Anki cloze format like "{{{{c1::word}}}}". Never do this.

            Respond ONLY with a JSON array of objects. Keys required exactly as follows:
            "word", "english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation".
            """
            
            var_name, cur_key, cur_model = self.key_manager.get_next_key_model()
            self.key_manager.record_attempt(var_name)
            
            try:
                t0 = time.time()
                raw_text, tokens = self._call_api_raw(prompt, cur_key, cur_model)
                self.key_manager.record_success(var_name, cur_model, time.time() - t0, tokens)
                
                if raw_text.startswith("```json"):
                    raw_text = raw_text[7:]
                elif raw_text.startswith("```"):
                    raw_text = raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                    
                for res in json.loads(raw_text.strip()):
                    w_key = res.get("word", "").strip().lower()
                    if w_key in [m['word'].strip().lower() for m in missing] and self._is_valid_result(res):
                        acc_results[w_key] = res
                    
                if len(acc_results) < len(chunk): 
                    time.sleep(1) 
                    
            except requests.exceptions.HTTPError as err:
                status_code = err.response.status_code
                if status_code == 429:
                    self.ui.thread_progress.update(task_id, status="[red]Bị Rate Limit! Ép nhảy Model...[/]")
                    # Bỏ luôn thuật toán Banned, không cần gọi penalize_key nữa để tránh tốn thời gian.
                    # Hệ thống sẽ tự động cấp Model khác ở lượt while tiếp theo.
                    
                    # --- PHẢI CÓ DÒNG NÀY ĐỂ ÉP HỆ THỐNG ĐỔI SANG KEY/MODEL KHÁC ---
                    self.key_manager.penalize_key(var_name)
                else:
                    try: 
                        error_msg = err.response.json().get('error', {}).get('message', 'Unknown Error')
                    except: 
                        error_msg = str(err)
                    self.ui.thread_progress.update(task_id, status=f"[bold red]API Error {status_code}: {error_msg[:30]}...[/]")
                time.sleep(2) 
            except json.decoder.JSONDecodeError:
                self.ui.thread_progress.update(task_id, status="[bold red]Lỗi Code: AI trả JSON sai định dạng![/]")
                time.sleep(2)
            except ValueError as ve:
                self.ui.thread_progress.update(task_id, status=f"[bold yellow]Model Alert: {str(ve)[:40]}...[/]")
                time.sleep(2)
            except Exception as e:
                self.ui.thread_progress.update(task_id, status=f"[bold red]Lỗi Code: {type(e).__name__}[/]")
                time.sleep(2)
                
        return acc_results                                                
    
    def _process_chunk(self, chunk):
        with self.worker_lock:
            worker_id = self.available_workers.pop(0)
            task_id = self.ui.worker_tasks[worker_id]
            
        self.ui.thread_progress.update(task_id, completed=0, total=len(chunk), status="[cyan]Processing AI...")
        ai_results = self._enrich_chunk_with_multi_keys(chunk, task_id)
        self.ui.thread_progress.update(task_id, status="[cyan]Formatting...")
        
        processed = []
        for item in chunk:
            wk = item['word'].strip().lower()
            if wk not in ai_results:
                with self.failed_words_lock:
                    if item['word'] not in self.failed_words: self.failed_words.append(item['word'])

            data = ai_results.get(wk, {'english_definition': 'N/A', 'part_of_speech': 'N/A', 'example_front': 'N/A', 'example_back': 'N/A', 'example_vietnamese_translation': 'N/A'})
            processed.append({
                'index': item['index'], 'target_word': item['word'], 'ipa': item['ipa'], 'vietnamese_meaning': item['meaning'],
                'english_definition': data['english_definition'], 'part_of_speech': data['part_of_speech'],
                'example_front': data['example_front'], 'example_back': data['example_back'], 'example_vietnamese_translation': data['example_vietnamese_translation']
            })
            self.ui.thread_progress.update(task_id, advance=1)
            
        self.ui.thread_progress.update(task_id, status="[dim green]Done!")
        with self.worker_lock: self.available_workers.append(worker_id)
        return processed

    def run(self, excel_file, sheet_name, output_csv_name):
        if not os.path.isabs(excel_file): excel_file = os.path.join(self.base_dir, excel_file)
        out_path = os.path.join(self.export_dir, output_csv_name)

        try:
            df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
            ipa_row, ipa_col = next(((r, c) for r, row in df.iterrows() for c, v in row.items() if str(v).strip().lower() == 'ipa'), (-1, -1))
            if ipa_row == -1: return console.print("❌ [red]Không tìm thấy cột 'IPA' trong Excel![/]")

            existing, all_res, to_proc = self._load_checkpoint(out_path), [], []
            w_col, m_col, e_col = ipa_col - 1, ipa_col + 1, ipa_col + 2

            for r_idx in range(ipa_row + 1, len(df)):
                row = df.iloc[r_idx]
                w = str(row[w_col]).strip() if pd.notna(row[w_col]) else ""
                if w and w.lower() not in ['nan', 'none', '']:
                    wk = w.lower()
                    if wk in existing:
                        existing[wk]['index'] = r_idx 
                        all_res.append(existing[wk])
                    else:
                        to_proc.append({'index': r_idx, 'word': w, 'ipa': str(row[ipa_col]).strip() if pd.notna(row[ipa_col]) else "", 'meaning': str(row[m_col]).strip() if pd.notna(row[m_col]) else "", 'example': str(row[e_col]).strip() if e_col < len(row) and pd.notna(row[e_col]) else ""})

            if not to_proc: return console.print(f"🎉 [green]Đã hoàn thành 100% sheet '{sheet_name}'![/]")

            c_size = self.config["CHUNK_SIZE"]
            chunks = [to_proc[i:i + c_size] for i in range(0, len(to_proc), c_size)]
            console.print(f"🚀 [magenta]BẮT ĐẦU: {self.num_workers} Workers xử lý {len(to_proc)} từ...[/]")

            with Live(self.ui.layout, refresh_per_second=10):
                self.ui.global_progress.update(self.ui.global_task, total=len(to_proc), visible=True)
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                    futures = [executor.submit(self._process_chunk, c) for c in chunks]
                    while futures:
                        self.ui.update_keys_panel(self.key_manager)
                        done, not_done = concurrent.futures.wait(futures, timeout=0.1)
                        for f in done:
                            try:
                                res = f.result()
                                all_res.extend(res)
                                self.ui.global_progress.update(self.ui.global_task, advance=len(res)) 
                                self._save_progress(all_res, out_path)
                            except: pass
                            finally: futures.remove(f)

            console.print("\n" + "="*50)
            self._save_progress(all_res, out_path) 
            
            if self.failed_words:
                console.print(f"\n⚠️ [yellow]CÓ {len(self.failed_words)} TỪ BỊ LỖI (Đã gán N/A):[/]")
                for fw in self.failed_words: console.print(f"   [red]✖ {fw}[/]")
            else:
                console.print("\n✨ [green]Tuyệt vời! Thành công 100%, không có từ lỗi.[/]")
                
        except Exception as e:
            console.print(f"\n❌ [red]CRASH: {e}[/]")
