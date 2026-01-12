import re
import os
import tkinter as tk
from tkinter import filedialog

def clean_content(content):
    """
    Làm sạch nội dung file:
    1. Xóa tag rác.
    2. Xóa xuống dòng để đưa về dạng stream (dòng chảy).
    """
    # --- SỬA LỖI TẠI ĐÂY ---
    # Dùng r"..." (ngoặc kép) để an toàn hơn, tránh lỗi SyntaxError
    content = re.sub(r"\\", "", content, flags=re.DOTALL)
    
    # Thay thế xuống dòng bằng khoảng trắng
    content = content.replace('\n', ' ').replace('\r', ' ')
    # Xóa khoảng trắng kép
    content = re.sub(r"\s+", " ", content).strip()
    return content

def extract_value_from_def(def_tokens):
    """
    Trích xuất giá trị linh kiện từ chuỗi định nghĩa.
    Format: FOOTPRINT ! PART ! VALUE
    """
    def_str = " ".join(def_tokens)
    parts = def_str.split('!')
    
    val = "NM" # No Model
    
    # Logic: Lấy phần tử cuối cùng có dữ liệu sau dấu !
    if len(parts) >= 2:
        raw_val = parts[-1].strip()
        # Nếu phần tử cuối rỗng, lùi lại kiểm tra phần trước đó
        if not raw_val and len(parts) >= 3:
            raw_val = parts[-2].strip()
            
        if raw_val:
            val = raw_val
            
    # Làm sạch dấu nháy đơn '10k' -> 10k
    val = val.replace("'", "")
    return val

def parse_telesis(content):
    if "$NETS" not in content:
        raise ValueError("File không đúng định dạng (Thiếu $NETS)")

    chunks = content.split("$NETS")
    
    # --- XỬ LÝ PACKAGES ---
    pkg_chunk = chunks[0]
    if "$PACKAGES" in pkg_chunk:
        pkg_chunk = pkg_chunk.split("$PACKAGES")[1]
        
    components = {} 
    
    # Cắt theo dấu chấm phẩy ;
    segments = pkg_chunk.split(';')
    
    # Segment đầu tiên luôn là Definition
    current_def_tokens = segments[0].strip().split()
    current_val = extract_value_from_def(current_def_tokens)
    
    for i in range(1, len(segments)):
        segment = segments[i].strip()
        if not segment: continue
        
        tokens = segment.split()
        
        # Tìm điểm cắt giữa RefDes list và Definition tiếp theo
        split_idx = len(tokens)
        found_def = False
        
        for idx, token in enumerate(tokens):
            if '!' in token:
                if token.startswith('!'):
                    split_idx = max(0, idx - 1)
                else:
                    split_idx = idx
                found_def = True
                break
        
        ref_tokens = tokens[:split_idx]
        def_tokens = tokens[split_idx:]
        
        for ref in ref_tokens:
            components[ref] = current_val
            
        if found_def and def_tokens:
            current_val = extract_value_from_def(def_tokens)

    # --- XỬ LÝ NETS ---
    net_chunk = chunks[1]
    if "$SCHEDULE" in net_chunk:
        net_chunk = net_chunk.split("$SCHEDULE")[0]
        
    net_connections = {} 
    net_segments = net_chunk.split(';')
    
    current_net_name = net_segments[0].strip().replace("'", "")
    
    for i in range(1, len(net_segments)):
        segment = net_segments[i].strip()
        tokens = segment.split()
        
        if i < len(net_segments) - 1:
            next_net_name = tokens[-1].replace("'", "")
            pins = tokens[:-1]
        else:
            next_net_name = None
            pins = tokens
            
        for pin_str in pins:
            ref = ""
            pin = ""
            if '.' in pin_str:
                ref, pin = pin_str.split('.', 1)
            elif '-' in pin_str:
                ref, pin = pin_str.split('-', 1)
            
            if ref:
                if ref not in net_connections:
                    net_connections[ref] = {}
                net_connections[ref][pin] = current_net_name
                
        current_net_name = next_net_name

    return components, net_connections

def write_ltspice(components, connections, output_path):
    lines = []
    lines.append(f"* LTspice Netlist: {os.path.basename(output_path)}")
    lines.append("* Converted from Telesis format")
    lines.append("")
    
    sorted_refs = sorted(components.keys())
    
    for ref in sorted_refs:
        val = components[ref]
        
        # Chuẩn hóa 1M -> 1Meg cho điện trở
        val_upper = val.upper()
        if ref.startswith('R') and val_upper.endswith('M') and not val_upper.endswith('MEG'):
            val = val + "eg"
            
        comp_pins = connections.get(ref, {})
        if not comp_pins:
            lines.append(f"* {ref} ({val}) - No connections found")
            continue
            
        # Sort chân theo số (1, 2, 3...)
        def pin_sort_key(k):
            return int(k) if k.isdigit() else k
            
        sorted_pin_keys = sorted(comp_pins.keys(), key=pin_sort_key)
        net_list = [comp_pins[p] for p in sorted_pin_keys]
        nodes_str = " ".join(net_list)
        
        prefix = ref[0].upper()
        line = ""
        
        if prefix in ['R', 'L', 'C', 'Q', 'D']:
             # R, L, C, Q, D xuất dạng chuẩn
            line = f"{ref} {nodes_str} {val}"
        else:
            # Các loại khác (U, J...) xuất dạng Subcircuit X
            model_name = val if (val and val != "NM") else f"Model_{ref}"
            line = f"X{ref} {nodes_str} {model_name}"
            
        lines.append(line)

    lines.append("")
    lines.append(".end")
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))
        return True
    except Exception as e:
        print(f"Lỗi khi ghi file: {e}")
        return False

def main():
    root = tk.Tk()
    root.withdraw()
    
    print("--- TOOL CHUYỂN ĐỔI NETLIST ---")
    print("Vui lòng chọn file .tel hoặc .txt từ cửa sổ hiện ra...")
    
    file_path = filedialog.askopenfilename(
        title="Chọn file Netlist gốc",
        filetypes=[("All Files", "*.*")]
    )
    
    if not file_path:
        print("Đã hủy chọn file.")
        return

    print(f"Đang xử lý file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        clean_data = clean_content(content)
        comps, nets = parse_telesis(clean_data)
        
        folder = os.path.dirname(file_path)
        filename = os.path.splitext(os.path.basename(file_path))[0]
        output_path = os.path.join(folder, filename + ".cir")
        
        if write_ltspice(comps, nets, output_path):
            print("\n" + "="*30)
            print("ĐÃ XONG!")
            print(f"File kết quả: {output_path}")
            print("="*30)
            
    except Exception as e:
        print("\nCÓ LỖI XẢY RA:")
        print(e)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
    input("\nNhấn Enter để thoát...")