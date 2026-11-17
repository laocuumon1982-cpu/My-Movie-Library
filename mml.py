"""My Movie Library — điểm khởi chạy: mở giao diện web (pywebview); nếu máy không chạy được thì dùng giao diện Tk."""
import sys


def main():
    if sys.platform == 'win32':
        try:
            import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    ok = False
    try:
        import webapp
        ok = webapp.run_web()
    except Exception:
        ok = False
    if not ok:
        import app
        app.run_tk()


if __name__ == '__main__':
    main()
