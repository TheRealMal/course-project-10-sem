from datetime import datetime

class BaseLogger:
    def _log_err(self, msg: str) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    
    def _log(self, msg: str) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")