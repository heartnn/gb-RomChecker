# gb-RomChecker

判断rom是gb还是gbc

先安装依赖

```
pip install tqdm wcwidth
```

然后把rom文件拖放到RomChecker.py即可，支持gb、gbc、zip、7z，当拖放压缩文件时，会处理里面所有的gb和gbc文件。

结果会显示当前的扩展名是否正确。

可用pyinstaller打包成exe，把RomChecker.py和7za.exe放在同一文件夹下，然后执行：

```
pyinstaller --onefile --console --name RomChecker ^
  --add-binary "7za.exe;." ^
  --hidden-import tqdm --hidden-import tqdm.std --hidden-import colorama ^
  --hidden-import wcwidth ^
  --noupx ^
  RomChecker.py
```
