
from time import time

from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import (
    Progress, BarColumn, TextColumn, 
    TimeElapsedColumn, TimeRemainingColumn, SpinnerColumn
)
from rich.console import Console, Group
from rich.table import Table
from rich.progress_bar import ProgressBar

# 1. LỚP QUẢN LÝ GIAO DIỆN (UI MANAGER)
# ==========================================


class DashboardUI:
    def __init__(self, num_threads):
        self.layout = Layout()
        self.layout.split_column(Layout(name="header", size=5), Layout(name="body"))
        self.layout["body"].split_row(Layout(name="left", ratio=1), Layout(name="right", ratio=2))
        
        self.global_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None, complete_style="white", finished_style="white"), 
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("[cyan]{task.completed}/{task.total} words"),
            TimeElapsedColumn(), TimeRemainingColumn()
        )
        self.global_task = self.global_progress.add_task("GLOBAL PROGRESS", total=100, visible=False)

        self.thread_progress = Progress(
            SpinnerColumn(), TextColumn("[bold green]{task.description}"),
            BarColumn(complete_style="white", finished_style="white"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.fields[status]}")
        )
        
        self.worker_tasks = [
            self.thread_progress.add_task(f"Thread {i+1}", total=100, status="[dim]Idle") 
            for i in range(num_threads)
        ]

        self.layout["header"].update(Panel(self.global_progress, title="🌟 TRẠNG THÁI TỔNG THỂ", border_style="blue"))
        self.layout["left"].update(Panel(self.thread_progress, title="⚙️ TIẾN ĐỘ THREADS", border_style="green"))
        self.layout["right"].update(Panel("Loading...", title="🔑 API KEY COOLDOWN", border_style="yellow"))

    def update_keys_panel(self, key_manager):
        try:
            current_time = time()
            all_keys_ui = []
            
            for var_name, _ in key_manager.keys_info:
                active_m = key_manager.active_model_display.get(var_name, "Waiting...")
                quota_str = "[dim]Waiting...[/]"
                
                if active_m in key_manager.trackers.get(var_name, {}):
                    tr = key_manager.trackers[var_name][active_m]
                    rpm_used = len([t for t in tr.rpm_window if current_time - t < 60])
                    quota_str = f"[bold blue]RPM: {rpm_used}/{tr.limit_rpm}[/] | [bold magenta]RPD: {tr.rpd_count}/{tr.limit_rpd}[/]"

                cd = key_manager.current_cd.get(var_name, 5.0)
                consec_429 = key_manager.consecutive_429.get(var_name, 0)
                cur_active_cd = min(60.0, 5.0 * (2 ** (consec_429 - 1))) if consec_429 > 0 else cd
                
                remaining = key_manager.cooldown_until.get(var_name, 0) - current_time
                s = key_manager.stats.get(var_name, {}).get('success', 0)
                t = key_manager.stats.get(var_name, {}).get('total', 0)
                
                if remaining > 0:
                    display_rem = min(remaining, cur_active_cd) if cur_active_cd > 0 else remaining
                    completed = cur_active_cd - display_rem
                    ban_rem = key_manager.ui_ban_until.get(var_name, 0) - current_time
                    status_text = f"[bold red]Banned {ban_rem:.1f}s[/]" if consec_429 > 0 and ban_rem > 0 else f"[red]Wait {remaining:.1f}s[/]"
                else:
                    completed, status_text = cur_active_cd, "[green]Ready[/]"
                
                # --- Ép kiểu an toàn chống crash cho ProgressBar ---
                total_bar = float(cur_active_cd) if cur_active_cd > 0 else 1.0
                completed_bar = float(completed) if completed > 0 else 0.0

                t1 = Table(show_header=False, box=None, padding=(0, 1), expand=True)
                t1.add_column(width=26, no_wrap=True)
                t1.add_column(justify="center")
                t1.add_column(justify="right", no_wrap=True) 
                
                t1.add_row(
                    f"[bold yellow]{var_name[:26]}[/]", 
                    ProgressBar(total=total_bar, completed=completed_bar, complete_style="white"), 
                    f"[bold cyan][{s}/{t}][/] {status_text}"
                )
                t2 = f"   [dim]└─[/] [yellow]{active_m}[/] | {quota_str} | [magenta]Avg: {cd:.1f}s[/]\n"
                all_keys_ui.append(Group(t1, t2))
                
            self.layout["right"].update(Panel(Group(*all_keys_ui), title="🔑 API KEY COOLDOWN", border_style="yellow"))
            
        except Exception as e:
            # Nếu code vẽ UI bị lỗi, nó sẽ in thẳng ra bảng bên phải để bắt bệnh!
            self.layout["right"].update(Panel(f"[bold red]Lỗi Render UI:[/]\n{e}", title="🔑 API KEY COOLDOWN", border_style="red"))