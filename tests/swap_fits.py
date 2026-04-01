import os
import sys
from astropy.io import fits

def swap_fits_content(file1_path, file2_path, out1_path, out2_path):
    """
    仅交换两个FITS文件的头文件(Header)，保持各自的数据(Data)不变，并将结果保存为两个新文件。
    """
    if not os.path.exists(file1_path) or not os.path.exists(file2_path):
        print("错误：找不到指定的 FITS 文件。")
        return

    print(f"正在读取 {file1_path}...")
    with fits.open(file1_path) as hdul1:
        # 深拷贝以防止在关闭文件后丢失数据
        hdu1_data = hdul1[0].data.copy() if hdul1[0].data is not None else None
        hdu1_header = hdul1[0].header.copy()
        
    print(f"正在读取 {file2_path}...")
    with fits.open(file2_path) as hdul2:
        hdu2_data = hdul2[0].data.copy() if hdul2[0].data is not None else None
        hdu2_header = hdul2[0].header.copy()

    print("正在交换头文件...")
    
    # 交换操作：向 out1 中写入 file1 的数据 和 file2 的头
    new_hdu1 = fits.PrimaryHDU(data=hdu1_data, header=hdu2_header)
    new_hdul1 = fits.HDUList([new_hdu1])
    new_hdul1.writeto(out1_path, overwrite=True)
    print(f"已将 {file2_path} 的头文件保存至 {out1_path}")

    # 交换操作：向 out2 中写入 file2 的数据 和 file1 的头
    new_hdu2 = fits.PrimaryHDU(data=hdu2_data, header=hdu1_header)
    new_hdul2 = fits.HDUList([new_hdu2])
    new_hdul2.writeto(out2_path, overwrite=True)
    print(f"已将 {file1_path} 的头文件保存至 {out2_path}")

if __name__ == "__main__":
    # 获取脚本所在的目录，设定默认的测试文件路径
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_f1 = os.path.join(base_dir, "gen.fits")
    default_f2 = os.path.join(base_dir, "raw.FITS")
    
    # 支持命令行参数
    if len(sys.argv) >= 3:
        f1 = sys.argv[1]
        f2 = sys.argv[2]
    else:
        f1 = default_f1
        f2 = default_f2

    # 生成输出文件的名称
    o1 = f1.replace(".fits", "_swapped.fits")
    o2 = f2.replace(".fits", "_swapped.fits")
    
    swap_fits_content(f1, f2, o1, o2)
