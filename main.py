# main.py - 完整程序入口
try:
    import tkinter as tk
    from main_gui import ProxyGUI
    
    if __name__ == "__main__":
        root = tk.Tk()
        app = ProxyGUI(root)
        root.mainloop()
        
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保安装了所有必需的包")
    
except Exception as e:
    print(f"运行时错误: {e}")
