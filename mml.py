"""My Movie Library — điểm khởi chạy: mở giao diện web (pywebview); nếu máy không chạy được thì dùng giao diện Tk."""
import sys


def main():
    if '--force-eject' in sys.argv:                      # chạy bằng quyền Admin chỉ để ép tháo ổ
        i = sys.argv.index('--force-eject')
        import postscan
        postscan.eject_cli(sys.argv[i + 1], sys.argv[i + 2]); return
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
