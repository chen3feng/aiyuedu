# /// script
# requires-python = ">=3.9"
# ///
"""下载并解压分级阅读所需的原始词库数据（压缩后约 270MB，解压后约 875MB）。

拉取四类 raw 数据到 data/wordlists/raw/：

- ecdict.csv            ECDICT 全量 CSV（MIT）→ process_ecdict.py 生成 wordlist.csv
- lemma.en.txt          ECDICT 词形还原表（MIT）→ build_surface_lemma.py 的屈折来源
- ecdict-sqlite-28.zip  ECDICT SQLite（MIT，解压出 stardict.db，约 811MB）
                        → 后台「多词表达式/术语识别」的运行时依赖（settings.ecdict_path）
- BNC_COCA_25000.zip    Paul Nation BNC/COCA 25000 词族表（CC BY-SA 4.0）
                        → wordlist.csv 的 rank + surface_lemma.json 的派生来源

幂等：已存在且 SHA256 一致的文件跳过下载；不一致则重新下载。下载先写 .part 临时文件，
校验通过后改名，中断不会留下半截文件冒充完整数据。解压按成员名覆盖、已解压则跳过。

运行（项目根目录）：
    uv run data/wordlists/download_raw.py
    # 或：python data/wordlists/download_raw.py

完整初始化词表：
    uv run data/wordlists/download_raw.py        # 1. 拉取 raw
    uv run data/wordlists/process_ecdict.py      # 2. raw → wordlist.csv
    uv run data/wordlists/build_surface_lemma.py # 3. raw → surface_lemma.json

注意：raw/ 已在 .gitignore 中，不入库；脚本本身入库，供全新 clone 一键拉取。
"""
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"

# 数据源：url、文件名、SHA256（本仓库上次构建时的已知好版本）、解压策略、授权。
# 若上游更新导致校验失败，先人工确认新版本无碍，再更新对应 sha256。
SOURCES = [
    {
        "name": "ecdict.csv",
        "url": "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv",
        "sha256": "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf",
        "extract": None,
        "license": "MIT",
    },
    {
        "name": "lemma.en.txt",
        "url": "https://raw.githubusercontent.com/skywind3000/ECDICT/master/lemma.en.txt",
        "sha256": "e255b097404e3e0052060e2ddf6e15a1414f577071d63d51d2ca0ce9dacee0fc",
        "extract": None,
        "license": "MIT",
    },
    {
        "name": "ecdict-sqlite-28.zip",
        "url": "https://github.com/skywind3000/ECDICT/releases/download/1.0.28/ecdict-sqlite-28.zip",
        "sha256": "ea01f76a3b3351021ce47077e89234465cc9441c8793054495320d06c0c3f3f6",
        "extract": "stardict.db",  # 仅解压这一成员
        "license": "MIT",
    },
    {
        "name": "BNC_COCA_25000.zip",
        "url": "https://www.wgtn.ac.nz/lals/resources/paul-nations-resources/vocabulary-analysis-programs/range/BNC_COCA_25000.zip",
        "sha256": "ac81c7a60e5c76cd2bbf0c59b0501808f0d4fa026b2936919dd54329a9bb6a69",
        "extract": "*",  # 解压全部（basewrd1..34.txt / range.txt / Range32H.exe）
        "license": "CC BY-SA 4.0",
    },
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, label: str) -> None:
    tmp = dest.with_name(dest.name + ".part")
    tmp.unlink(missing_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "aiyuedu/wordlist-init"})
    last_pct = -1
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as out:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        if pct != last_pct:
                            last_pct = pct
                            print(
                                f"\r  {label}: {done / 1048576:.0f}/{total / 1048576:.0f} MB ({pct}%)",
                                end="", flush=True,
                            )
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"× 下载 {label} 失败：{e}")
    print()
    tmp.replace(dest)


def _extract(zip_path: Path, member: str) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        if member == "*":
            targets = zf.namelist()
        else:
            targets = [n for n in zf.namelist() if Path(n).name == member]
        if not targets:
            raise SystemExit(f"× {zip_path.name} 中未找到成员「{member}」")
        missing = [
            n for n in targets
            if not (RAW / Path(n).name).exists() or (RAW / Path(n).name).stat().st_size == 0
        ]
        if not missing:
            print(f"√ {zip_path.name} 已全部解压（{len(targets)} 个文件）")
            return
        for name in missing:
            dest = RAW / Path(name).name  # 压平到 raw/（zip 内无子目录）
            print(f"  解压 {Path(name).name} …")
            with zf.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for src in SOURCES:
        dest = RAW / src["name"]
        if dest.exists() and sha256_file(dest) == src["sha256"]:
            print(f"√ {src['name']} 已存在且校验通过，跳过")
        else:
            if dest.exists():
                print(f"! {src['name']} 已存在但校验不符，重新下载")
            print(f"↓ 下载 {src['name']}（{src['license']}）")
            _download(src["url"], dest, src["name"])
            if sha256_file(dest) != src["sha256"]:
                dest.unlink(missing_ok=True)
                raise SystemExit(f"× {src['name']} 下载后 SHA256 校验失败，已删除，请重试")
            print(f"√ {src['name']} 下载完成")
        if src.get("extract"):
            _extract(dest, src["extract"])
    print("完成。下一步：uv run data/wordlists/process_ecdict.py && "
          "uv run data/wordlists/build_surface_lemma.py")


if __name__ == "__main__":
    main()
