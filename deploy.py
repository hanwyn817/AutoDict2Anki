import os
import shutil
import subprocess
import sys
import zipfile


def create_virtualenv(env_dir: str) -> None:
    """创建 virtualenv 虚拟环境。"""
    if not os.path.exists(env_dir):
        print(f"Creating virtual environment at {env_dir}...")
        subprocess.check_call([sys.executable, "-m", "venv", env_dir])
    else:
        print(f"Virtual environment already exists at {env_dir}.")


def resolve_pip_path(env_dir: str) -> str:
    if os.name == "nt":
        pip_path = os.path.join(env_dir, "Scripts", "pip.exe")
    else:
        pip_path = os.path.join(env_dir, "bin", "pip")
    if not os.path.exists(pip_path):
        raise FileNotFoundError(f"未找到 pip 可执行文件: {pip_path}")
    return pip_path


def resolve_site_packages_dir(env_dir: str) -> str:
    if os.name == "nt":
        site_packages = os.path.join(env_dir, "Lib", "site-packages")
    else:
        py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        site_packages = os.path.join(env_dir, "lib", py_ver, "site-packages")
    if not os.path.exists(site_packages):
        raise FileNotFoundError(f"未找到 site-packages 目录: {site_packages}")
    return site_packages


def install_requirements(env_dir: str, requirements_file: str) -> None:
    """安装 requirements.txt 中的依赖。"""
    print("Installing dependencies...")
    pip_path = resolve_pip_path(env_dir)
    subprocess.check_call([pip_path, "install", "-r", requirements_file])


def zip_directory(zip_filename: str, directory: str) -> None:
    """将指定目录压缩成 ZIP 文件。"""
    print(f"Zipping directory {directory}...")
    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(directory):
            for file_name in files:
                full_path = os.path.join(root, file_name)
                arcname = os.path.relpath(full_path, directory)
                zipf.write(full_path, arcname)


def copy_runtime_files(project_root: str, temp_dir: str) -> None:
    """拷贝项目根目录中的运行时 Python 文件。"""
    for item in os.listdir(project_root):
        item_path = os.path.join(project_root, item)
        if not os.path.isfile(item_path):
            continue
        if not item.endswith(".py"):
            continue
        if item == "deploy.py" or item.startswith("test_"):
            continue
        shutil.copy(item_path, os.path.join(temp_dir, item))


def create_deployment_package() -> None:
    """构建 Lambda 部署包。"""
    project_root = os.getcwd()
    env_dir = os.path.join(project_root, "venv")
    requirements_file = os.path.join(project_root, "requirements.txt")
    zip_filename = os.path.join(project_root, "lambda_deployment_package.zip")

    create_virtualenv(env_dir)
    install_requirements(env_dir, requirements_file)

    temp_dir = os.path.join(project_root, "temp_deployment")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    site_packages_dir = resolve_site_packages_dir(env_dir)
    for item in os.listdir(site_packages_dir):
        item_path = os.path.join(site_packages_dir, item)
        dest_path = os.path.join(temp_dir, item)
        if os.path.isdir(item_path):
            shutil.copytree(item_path, dest_path, dirs_exist_ok=True)
        else:
            shutil.copy(item_path, dest_path)

    copy_runtime_files(project_root, temp_dir)

    resources_dir = os.path.join(project_root, "resources")
    if os.path.exists(resources_dir):
        shutil.copytree(resources_dir, os.path.join(temp_dir, "resources"), dirs_exist_ok=True)

    shutil.copy(requirements_file, temp_dir)
    zip_directory(zip_filename, temp_dir)

    print(f"Deployment package created: {zip_filename}")


if __name__ == "__main__":
    create_deployment_package()
