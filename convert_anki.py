import os
import sys
import pandas as pd
import json
import time
import requests
import threading
import concurrent.futures
import datetime
from dotenv import dotenv_values

# Import Rich thay cho tqdm
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import (
    Progress, BarColumn, TextColumn, 
    TimeElapsedColumn, TimeRemainingColumn, SpinnerColumn
)
from rich.console import Console

# ==========================================
# ⚙️ SYSTEM CONFIGURATION (TÙY CHỈNH Ở ĐÂY)
# ==========================================


# ==========================================
# 🧠 ALL MODELS RATE LIMIT CONFIGURATION (TỪ ẢNH CỦA BẠN)
# ==========================================
# Ghi chú: TPM của Gemma 4 báo "Unlimited", ta set 999999 để logic code không bị vướng
GEMINI_MODELS_CONFIG = {
    # 👑 NHÓM GEMINI (Thông minh nhất, tuân thủ JSON 100%, gánh team chính)
    "gemini-3.1-flash-lite-preview":    {"RPM": 15, "TPM": 250000, "RPD": 500},
    "gemini-2.5-flash-lite-preview":    {"RPM": 10, "TPM": 250000, "RPD": 20},
    "gemini-3-flash-preview":           {"RPM": 5,  "TPM": 250000, "RPD": 20},
    "gemini-2.5-flash-preview":         {"RPM": 5,  "TPM": 250000, "RPD": 20},

    # 🚀 NHÓM GEMMA 4 (Độ thông minh tốt, TPM không giới hạn, Quota RPD ngon)
    "gemma-4-31b":              {"RPM": 15, "TPM": 999999, "RPD": 1500},
    "gemma-4-26b":              {"RPM": 15, "TPM": 999999, "RPD": 1500},

    # 🚜 NHÓM GEMMA 3 (Cày cuốc siêu trâu bò, nhưng TPM 15K cực thấp)
    "gemma-3-27b":              {"RPM": 30, "TPM": 15000,  "RPD": 14400},
    "gemma-3-12b":              {"RPM": 30, "TPM": 15000,  "RPD": 14400},
    
    # ⚠️ HÀNG KHUYẾN CÁO: Rất dễ vỡ cấu trúc JSON do model quá bé (Chỉ nên làm backup cuối)
    "gemma-3-4b":               {"RPM": 30, "TPM": 15000,  "RPD": 14400},
    "gemma-3-2b":               {"RPM": 30, "TPM": 15000,  "RPD": 14400},
    "gemma-3-1b":               {"RPM": 30, "TPM": 15000,  "RPD": 14400}
}

CHUNK_SIZE = 5            
MAX_RETRIES_AI = 30       
API_KEY_COOLDOWN = 5

INPUT_EXCEL_FILE = "../Vocab_mountain_Writting.xlsm"
SHEET_NAME = "Day 9"
OUTPUT_CSV_FILE = "day9_turbo_absolute.csv"

console = Console()

# ==========================================
# 0. KHỞI TẠO GIAO DIỆN RICH (DASHBOARD)
# ==========================================
# 1. Global Progress
global_progress = Progress(
    TextColumn("[bold blue]{task.description}"),
    BarColumn(bar_width=None, complete_style="white", finished_style="white"), 
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TextColumn("[cyan]{task.completed}/{task.total} words"),
    TimeElapsedColumn(),
    TimeRemainingColumn()
)
global_task_id = global_progress.add_task("GLOBAL PROGRESS", total=100, visible=False)

# 2. Thread Progress
thread_progress = Progress(
    SpinnerColumn(),
    TextColumn("[bold green]{task.description}"),
    BarColumn(complete_style="white", finished_style="white"),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TextColumn("{task.fields[status]}")
)

# 3. Key Progress (Cooldown)
key_progress = Progress(
    TextColumn("[bold yellow]{task.description}"),
    BarColumn(complete_style="white", finished_style="white"),
    TextColumn("{task.fields[avg_cd]}"), # Cột hiển thị Cooldown trung bình hiện tại
    TextColumn("{task.fields[quota]}"), # 🟢 THÊM CỘT NÀY ĐỂ HIỂN THỊ QUOTA/RPM
    TextColumn("{task.fields[stats]} {task.fields[status]}")
)

# Bố cục chia Row và Column
layout = Layout()
layout.split_column(
    Layout(name="header", size=5),
    Layout(name="body")
)
layout["body"].split_row(
    Layout(name="left"),
    Layout(name="right")
)
layout["header"].update(Panel(global_progress, title="🌟 TRẠNG THÁI TỔNG THỂ (GLOBAL)", border_style="blue"))
layout["left"].update(Panel(thread_progress, title="⚙️ TIẾN ĐỘ THREADS (WORKERS)", border_style="green"))
layout["right"].update(Panel(key_progress, title="🔑 API KEY COOLDOWN", border_style="yellow"))

# ==========================================
# 1. API KEY MANAGER & VALIDATOR
# ==========================================
def validate_and_load_keys():
    console.print("🔍 [bold cyan]Loading API Keys from .env file...[/]")
    env_dict = dotenv_values(".env")
    
    all_keys = [(k, str(v).strip()) for k, v in env_dict.items() if v and str(v).strip()]
    
    if not all_keys:
        console.print("❌ [bold red]CRITICAL ERROR: No API Keys found in .env file![/]")
        sys.exit(1)
        
    console.print(f"✅ [bold green]Loaded {len(all_keys)} keys (Skipped API validation to save quota).[/]")
    
    ans = console.input(f"\n❓ [bold cyan]Continue with {len(all_keys)} active keys? (yes/no): [/]")
    if ans.lower() not in ['y', 'yes']:
        console.print("👋 Exited program.")
        sys.exit(0)
        
    console.print("="*50 + "\n")
    return all_keys

API_KEYS = validate_and_load_keys()

class ModelRateTracker:
    def __init__(self, limit_rpm, limit_tpm, limit_rpd, current_rpd):
        self.limit_rpm = limit_rpm
        self.limit_tpm = limit_tpm
        self.limit_rpd = limit_rpd
        self.rpm_window = []  # Lưu timestamp
        self.tpm_window = []  # Lưu (timestamp, tokens)
        self.rpd_count = current_rpd

    def is_available(self, current_time):
        # 1. Đụng nóc ngày -> Cấm cửa vĩnh viễn hôm nay
        if self.rpd_count >= self.limit_rpd: return False
        
        # 2. Dọn rác quá 60 giây
        self.rpm_window = [t for t in self.rpm_window if current_time - t < 75]
        self.tpm_window = [item for item in self.tpm_window if current_time - item[0] < 75]
        
        # 3. Check chạm nóc Phút (trừ hao 1 đơn vị và 1000 tokens cho an toàn)
        if len(self.rpm_window) >= self.limit_rpm - 1: return False
        if sum(i[1] for i in self.tpm_window) >= self.limit_tpm - 1000: return False
        
        return True

    def pre_register(self, current_time):
        # Đặt gạch trước 1 slot và ước lượng 1000 tokens để Thread khác khỏi tranh
        self.rpm_window.append(current_time)
        self.tpm_window.append((current_time, 1000))

    def record_actual_usage(self, current_time, actual_tokens):
        # Cập nhật số token thực tế sau khi call xong và tăng RPD
        if self.tpm_window:
            self.tpm_window[-1] = (current_time, actual_tokens)
        self.rpd_count += 1

        
class KeyManager:
    def __init__(self, keys_info):
        self.keys_info = keys_info 
        self.lock = threading.Lock()
        
        # --- 1. SETUP MODEL QUOTA & JSON FILE ---
        self.today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        self.rpd_data = self._load_rpd()
        if self.today_str not in self.rpd_data:
            self.rpd_data[self.today_str] = {}
            
        self.model_names_list = list(GEMINI_MODELS_CONFIG.keys())
        self.global_model_index = 0
        self.active_model_display = {var_name: "Waiting..." for var_name, _ in keys_info}

        self.trackers = {}
        for var_name, _ in keys_info:
            if var_name not in self.rpd_data[self.today_str]:
                self.rpd_data[self.today_str][var_name] = {}
            self.trackers[var_name] = {}
            for m_name, m_cfg in GEMINI_MODELS_CONFIG.items():
                current_rpd = self.rpd_data[self.today_str][var_name].get(m_name, 0)
                self.trackers[var_name][m_name] = ModelRateTracker(m_cfg["RPM"], m_cfg["TPM"], m_cfg["RPD"], current_rpd)

        # --- 2. THUẬT TOÁN COOLDOWN (Giữ nguyên WMA chuẩn) ---
        self.current_cd = {var_name: float(API_KEY_COOLDOWN) for var_name, _ in keys_info}
        self.cooldown_until = {var_name: 0.0 for var_name, _ in keys_info}
        self.last_success_time = {var_name: 0.0 for var_name, _ in keys_info}
        self.stats = {var_name: {'total': 0, 'success': 0} for var_name, _ in keys_info}
        
        self.consecutive_429 = {var_name: 0 for var_name, _ in keys_info}
        self.consecutive_successes = {var_name: 0 for var_name, _ in keys_info}
        self.ui_ban_until = {var_name: 0.0 for var_name, _ in keys_info}
        self.window_size = 3 
        self.recent_durations = {var_name: [] for var_name, _ in keys_info}

        # --- 3. UI INIT ---
        self.key_tasks = {}
        for var_name, _ in keys_info:
            self.key_tasks[var_name] = key_progress.add_task(
                var_name, total=self.current_cd[var_name], status="[green]Ready", 
                stats="[cyan][0/0]", avg_cd=f"CD: {self.current_cd[var_name]:.1f}s", quota="[dim]Khởi động...[/]"
            )

    def _load_rpd(self):
        if os.path.exists("rpd_tracker.json"):
            try:
                with open("rpd_tracker.json", "r") as f: return json.load(f)
            except: pass
        return {}

    def _save_rpd(self):
        try:
            with open("rpd_tracker.json", "w") as f: json.dump(self.rpd_data, f, indent=4)
        except: pass

    def get_next_key_model(self):
        while True:
            with self.lock:
                current_time = time.time()
                current_global_model = self.model_names_list[self.global_model_index]
                
                selected_var, selected_key = None, None
                shortest_wait = float('inf')
                all_keys_exhausted_rpd = True # Biến kiểm tra xem cả 14 keys đã cạn RPD chưa

                for var_name, key in self.keys_info:
                    tracker = self.trackers[var_name][current_global_model]
                    
                    if tracker.rpd_count < tracker.limit_rpd:
                        all_keys_exhausted_rpd = False # Vẫn còn ít nhất 1 key chưa kiệt sức hôm nay
                        
                        if current_time < self.cooldown_until[var_name]:
                            wait_t = self.cooldown_until[var_name] - current_time
                            if wait_t < shortest_wait: shortest_wait = wait_t
                            continue

                        if tracker.is_available(current_time):
                            selected_var, selected_key = var_name, key
                            break

                if selected_var:
                    # Giao nhiệm vụ thành công
                    self.trackers[selected_var][current_global_model].pre_register(current_time)
                    self.cooldown_until[selected_var] = current_time + self.current_cd[selected_var]
                    self.active_model_display[selected_var] = current_global_model
                    return selected_var, selected_key, current_global_model

                if all_keys_exhausted_rpd:
                    # THỜI KHẮC CHUYỂN MODEL: Tất cả 14 keys đều hết RPD cho model này!
                    self.global_model_index += 1
                    if self.global_model_index >= len(self.model_names_list):
                        console.print("\n🛑 [bold red]HẾT CỨU! TOÀN BỘ KEYS ĐÃ DÙNG CẠN SẠCH QUOTA CỦA TẤT CẢ MODELS HÔM NAY![/]")
                        os._exit(1)
                    continue # Quay lại vòng lặp với model mới ngay lập tức

            # Nếu kẹt do RPM/TPM thì ráng đợi 1 giây rồi check lại
            time.sleep(min(1.0, shortest_wait if shortest_wait != float('inf') else 1.0))

    def record_success(self, var_name, model_name, duration, tokens):
        with self.lock:
            current_time = time.time()
            self.stats[var_name]['success'] += 1
            self.consecutive_successes[var_name] += 1
            if self.consecutive_successes[var_name] >= 2:
                self.consecutive_429[var_name] = 0 
            
            # --- WMA Tính trung bình chính xác dựa trên lần thành công ---
            safe_duration = min(duration, 60.0) 
            self.recent_durations[var_name].append(safe_duration)
            if len(self.recent_durations[var_name]) > self.window_size:
                self.recent_durations[var_name].pop(0)
                
            durations = self.recent_durations[var_name]
            n = len(durations)
            if n == 3: self.current_cd[var_name] = (durations[0]*1 + durations[1]*2 + durations[2]*3) / 6.0
            elif n == 2: self.current_cd[var_name] = (durations[0]*1 + durations[1]*2) / 3.0
            else: self.current_cd[var_name] = durations[0]
                
            self.last_success_time[var_name] = current_time

            # Update Model Quota & Save Backup
            self.trackers[var_name][model_name].record_actual_usage(current_time, tokens)
            self.rpd_data[self.today_str][var_name][model_name] = self.trackers[var_name][model_name].rpd_count
            self._save_rpd()

    def penalize_key(self, var_name):
        with self.lock:
            self.consecutive_successes[var_name] = 0
            self.consecutive_429[var_name] += 1
            backoff_time = min(60.0, 5.0 * (2 ** (self.consecutive_429[var_name] - 1)))
            target_time = time.time() + backoff_time
            self.cooldown_until[var_name] = target_time
            self.ui_ban_until[var_name] = target_time

    def record_attempt(self, var_name):
        with self.lock: self.stats[var_name]['total'] += 1

    def update_ui(self):
        current_time = time.time()
        for var_name, _ in self.keys_info:
            task_id = self.key_tasks[var_name]
            active_m = self.active_model_display[var_name]
            
            # Tính toán Quota hiển thị UI
            if active_m in self.trackers[var_name]:
                tr = self.trackers[var_name][active_m]
                rpm_used = len([t for t in tr.rpm_window if current_time - t < 60])
                quota_str = f"[bold yellow]{active_m}[/] | [bold blue]RPM: {rpm_used}/{tr.limit_rpm}[/] | [bold magenta]RPD: {tr.rpd_count}/{tr.limit_rpd}[/]"
            else:
                quota_str = "[dim]Waiting...[/]"

            # Xử lý thanh hiển thị
            if self.consecutive_429[var_name] > 0: current_active_cd = min(60.0, 5.0 * (2 ** (self.consecutive_429[var_name] - 1)))
            else: current_active_cd = self.current_cd[var_name]
                
            remaining = self.cooldown_until[var_name] - current_time
            s, t = self.stats[var_name]['success'], self.stats[var_name]['total']
            stats_str, avg_str = f"[bold cyan][{s}/{t}][/]", f"[magenta]Avg: {self.current_cd[var_name]:.1f}s[/]"
            
            if remaining > 0:
                display_rem = min(remaining, current_active_cd) if current_active_cd > 0 else remaining
                completed = current_active_cd - display_rem
                ban_remaining = self.ui_ban_until[var_name] - current_time
                if self.consecutive_429[var_name] > 0 and ban_remaining > 0: status_text = f"[bold red]Banned {ban_remaining:.1f}s"
                else: status_text = f"[red]Wait {remaining:.1f}s"
                
                key_progress.update(task_id, total=current_active_cd, completed=completed, status=status_text, stats=stats_str, avg_cd=avg_str, quota=quota_str)
            else:
                key_progress.update(task_id, total=self.current_cd[var_name], completed=self.current_cd[var_name], status="[green]Ready", stats=stats_str, avg_cd=avg_str, quota=quota_str)

key_pool = KeyManager(API_KEYS)

# ==========================================
# 2. CHECKPOINT & SAVE MANAGER
# ==========================================
file_write_lock = threading.Lock()

def load_checkpoint(output_csv):
    existing_data = {}
    if os.path.exists(output_csv):
        console.print(f"📂 Found existing checkpoint: '{os.path.basename(output_csv)}'. Verifying data integrity...")
        try:
            df_existing = pd.read_csv(output_csv)
            
            required_cols = ["target_word", "ipa", "vietnamese_meaning", "english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]
            for col in required_cols:
                if col not in df_existing.columns:
                    df_existing[col] = ""

            valid_count = 0
            for _, row in df_existing.iterrows():
                word = str(row.get('target_word', '')).strip().lower()
                print(f"🔍 Checking word: '{word}'...")
                if not word or word == 'nan': continue

                is_complete = True
                for col in ["english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]:
                    val = str(row.get(col, '')).strip()
                    if not val or val.lower() in ['nan', 'none', 'null', 'n/a', 'empty']:
                        print(f"⚠️ Incomplete data for word '{word}' in column '{col}'. This entry will be reprocessed.")
                        is_complete = False
                        break

                if is_complete:
                    existing_data[word] = row.to_dict()
                    valid_count += 1
                    
            console.print(f"✅ Recovered {valid_count} perfectly processed words. Skipping them!\n")
        except Exception as e:
            console.print(f"⚠️ [bold yellow]Failed to read checkpoint ({e}). Starting fresh.[/]\n")
            
    return existing_data

def save_progress(current_results, output_csv):
    with file_write_lock:
        sorted_res = sorted(current_results, key=lambda x: x.get('index', 0))
        save_list = [{k: v for k, v in r.items() if k != 'index'} for r in sorted_res]
        pd.DataFrame(save_list).to_csv(output_csv, index=False, encoding='utf-8')

# ==========================================
# 3. GEMINI API CALLER & VALIDATION
# ==========================================
def call_gemini_api_raw(prompt, api_key, model_name):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {}
    }
    
    # Chỉ ép strict JSON nếu là dòng họ nhà Gemini
    if "gemini" in model_name.lower():
        payload["generationConfig"]["responseMimeType"] = "application/json"
        
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status() 
    
    data = response.json()
    raw_text = ""
    try:
        candidates = data.get('candidates', [])
        if not candidates: raise ValueError(f"No candidates. Feedback: {data.get('promptFeedback', {})}")
        first_candidate = candidates[0]
        if 'content' not in first_candidate: raise ValueError(f"Blocked. Reason: {first_candidate.get('finishReason', 'UNKNOWN')}")
        parts = first_candidate.get('content', {}).get('parts', [])
        texts = [part.get('text', '') for part in parts if isinstance(part, dict) and 'text' in part]
        if not texts: raise ValueError("No text parts.")
        raw_text = "".join(texts)
    except Exception as e:
        raise ValueError(f"Unexpected JSON structure: {e}")

    # 🟢 Lấy chính xác Token Usage để quản lý TPM
    tokens = data.get('usageMetadata', {}).get('totalTokenCount', 1000)
    
    return raw_text.strip(), tokens

def is_valid_ai_result(res_dict):
    required_keys = ["english_definition", "part_of_speech", "example_front", "example_back", "example_vietnamese_translation"]
    invalid_placeholders = ["n/a", "none", "null", "blank", "empty"]
    
    for k in required_keys:
        if k not in res_dict: return False
        val = str(res_dict[k]).strip()
        if not val or len(val) < 2 or val.lower() in invalid_placeholders:
            return False
    return True

def enrich_chunk_with_multi_keys(chunk, thread_task_id):
    accumulated_results = {}
    attempt = 0
    
    while len(accumulated_results) < len(chunk) and attempt < MAX_RETRIES_AI:
        attempt += 1
        missing_items = [item for item in chunk if item['word'].strip().lower() not in accumulated_results]
        
        if attempt > 1:
            thread_progress.update(thread_task_id, status=f"[yellow]Retry #{attempt} (Fixing {len(missing_items)})[/]")
            
        input_data = [{"word": item['word'], "meaning": item['meaning'], "example": item['example']} for item in missing_items]
        
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
        
        var_name, current_key, current_model = key_pool.get_next_key_model()
        key_pool.record_attempt(var_name)
        
        try:
            start_api_time = time.time()
            # TRUYỀN THÊM TÊN MODEL VÀO HÀM API
            raw_text, used_tokens = call_gemini_api_raw(prompt, current_key, current_model)
            api_duration = time.time() - start_api_time 
            
            # GHI NHẬN THÀNH CÔNG VỚI ĐỦ CÁC THÔNG SỐ TOKEN VÀ MODEL
            key_pool.record_success(var_name, current_model, api_duration, used_tokens)

            # 2. XỬ LÝ DATA (Nếu có lỗi parse JSON ở đây thì API vẫn đã được tính là gọi thành công)
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
                
            results_list = json.loads(raw_text.strip())
            
            # 3. VALIDATE VÀ LƯU KẾT QUẢ
            for res in results_list:
                w_key = res.get("word", "").strip().lower()
                if w_key in [m['word'].strip().lower() for m in missing_items]:
                    if is_valid_ai_result(res):
                        accumulated_results[w_key] = res
                    
            if len(accumulated_results) < len(chunk):
                time.sleep(1) 
                
        except requests.exceptions.HTTPError as err:
            status_code = err.response.status_code
            if status_code == 429:
                thread_progress.update(thread_task_id, status="[red]Rate Limited! Penalty active[/]")
                key_pool.penalize_key(var_name)
            else:
                try:
                    error_msg = err.response.json().get('error', {}).get('message', 'Unknown Error')
                except:
                    error_msg = str(err)
                thread_progress.update(thread_task_id, status=f"[bold red]API Error {status_code}: {error_msg[:30]}...[/]")
            time.sleep(2) 
        except json.decoder.JSONDecodeError:
            thread_progress.update(thread_task_id, status="[bold red]Lỗi Code: AI trả JSON sai định dạng![/]")
            time.sleep(2)
        # BỔ SUNG: Bắt lỗi bóc tách JSON (ValueError từ call_gemini_api_raw)
        except ValueError as ve:
            thread_progress.update(thread_task_id, status=f"[bold yellow]Model Alert: {str(ve)[:40]}...[/]")
            time.sleep(2)
        except Exception as e:
            thread_progress.update(thread_task_id, status=f"[bold red]Lỗi Code: {type(e).__name__}[/]")
            time.sleep(2)

    return accumulated_results
# ==========================================
# 4. WORKER THREAD MANAGER
# ==========================================
max_workers = len(API_KEYS)
worker_tasks = []
for i in range(max_workers):
    worker_tasks.append(thread_progress.add_task(f"Thread {i+1}", total=CHUNK_SIZE, status="[dim]Idle"))

available_workers = list(range(max_workers))
worker_lock = threading.Lock()

def process_chunk(chunk_items):
    with worker_lock:
        worker_id = available_workers.pop(0)
        task_id = worker_tasks[worker_id]
        
    thread_progress.update(task_id, completed=0, total=len(chunk_items), status="[cyan]Processing AI...")

    ai_results_dict = enrich_chunk_with_multi_keys(chunk_items, task_id)
    
    thread_progress.update(task_id, status="[cyan]Formatting...")
    processed = []
    for item in chunk_items:
        word_key = item['word'].strip().lower()
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
        thread_progress.update(task_id, advance=1)
    
    thread_progress.update(task_id, status="[dim green]Done!")
    
    with worker_lock:
        available_workers.append(worker_id)
        
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
    print(f"🔍 Items to process: {items_to_process}")
    if total_missing == 0:
        console.print("🎉 [bold green]All words are already 100% completed in the CSV. Nothing left to do![/]")
        return all_results

    chunks = [items_to_process[i:i + CHUNK_SIZE] for i in range(0, total_missing, CHUNK_SIZE)]

    console.print(f"🚀 [bold magenta]STARTING TURBO MODE: {max_workers} Workers processing {total_missing} missing words...[/]")
    time.sleep(1)

    with Live(layout, refresh_per_second=10):
        global_progress.update(global_task_id, total=total_missing, visible=True)
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(process_chunk, chunk) for chunk in chunks]

                while futures:
                    key_pool.update_ui()
                    
                    done, not_done = concurrent.futures.wait(futures, timeout=0.1)
                    for future in done:
                        try:
                            chunk_result = future.result()
                            all_results.extend(chunk_result)
                            global_progress.update(global_task_id, advance=len(chunk_result)) 
                            save_progress(all_results, output_csv)
                        except Exception as exc:
                            pass
                        finally:
                            futures.remove(future)

        except Exception as exc:
            # Thay chữ 'pass' bằng dòng dưới đây để soi lỗi
            console.print(f"\n❌ [bold red]CRASH TRONG LUỒNG: {exc}[/]")

    console.print("\n" + "="*50)
    if len(all_results) < len(items_to_process):
        console.print("🛑 [bold red]INTERRUPTED BY USER![/]")
        console.print(f"💾 Completed chunks safely saved to '{os.path.basename(output_csv)}'.")
        sys.exit(0)

    all_results.sort(key=lambda x: x['index'])
    save_progress(all_results, output_csv) 
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
            console.print(f"\n🎉 [bold green]100% COMPLETENESS ACHIEVED! Results successfully saved at '{output_csv}'.[/]")
    except Exception as e:
        console.print(f"❌ [bold red]System Error: {e}[/]")

if __name__ == "__main__":
    run_import(INPUT_EXCEL_FILE, SHEET_NAME, OUTPUT_CSV_FILE)