import os
import shutil
import subprocess
import sys
import zipfile

def create_virtualenv(env_dir):
    """创建 virtualenv 虚拟环境"""
    if not os.path.exists(env_dir):
        print(f"Creating virtual environment at {env_dir}...")
        subprocess.check_call([sys.executable, "-m", "venv", env_dir])
    else:
        print(f"Virtual environment already exists at {env_dir}.")

def install_requirements(env_dir, requirements_file):
    """安装 requirements.txt 中的依赖"""
    print("Installing dependencies...")
    pip_path = os.path.join(env_dir, 'Scripts', 'pip')
    subprocess.check_call([pip_path, "install", "-r", requirements_file])

def zip_directory(zip_filename, directory, base_dir=None, include_folder=False):
    """将指定目录压缩成 ZIP 文件
    参数 include_folder: 是否包含目录本身（对于resources需要包含，其他情况不包含）
    """
    print(f"Zipping directory {directory}...")
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(directory):
            for file in files:
                full_path = os.path.join(root, file)
                # 如果include_folder是True，我们需要保留文件夹结构，否则不保留文件夹本身
                if include_folder:
                    arcname = os.path.relpath(full_path, base_dir)
                else:
                    arcname = os.path.relpath(full_path, directory)
                zipf.write(full_path, arcname)

def create_deployment_package():
    """构建 Lambda 部署包"""
    project_root = os.getcwd()
    env_dir = os.path.join(project_root, 'venv')  # 虚拟环境目录
    requirements_file = os.path.join(project_root, 'requirements.txt')
    zip_filename = os.path.join(project_root, 'lambda_deployment_package.zip')

    # Step 1: 创建并安装依赖
    create_virtualenv(env_dir)
    install_requirements(env_dir, requirements_file)

    # Step 2: 创建临时目录来存放 Lambda 部署包的内容
    temp_dir = os.path.join(project_root, 'temp_deployment')
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    # Step 3: 将依赖项、项目文件和资源文件拷贝到临时目录
    # 拷贝 venv/Lib/site-packages 中的所有文件（不包含文件夹本身）
    site_packages_dir = os.path.join(env_dir, 'Lib', 'site-packages')
    for item in os.listdir(site_packages_dir):
        item_path = os.path.join(site_packages_dir, item)
        if os.path.isdir(item_path):
            shutil.copytree(item_path, os.path.join(temp_dir, item), dirs_exist_ok=True)
        else:
            shutil.copy(item_path, temp_dir)

    # 拷贝 src 目录中的所有文件（不包含文件夹本身）
    src_dir = os.path.join(project_root, 'src')
    if os.path.exists(src_dir):
        for item in os.listdir(src_dir):
            item_path = os.path.join(src_dir, item)
            if os.path.isdir(item_path):
                shutil.copytree(item_path, os.path.join(temp_dir, item), dirs_exist_ok=True)
            else:
                shutil.copy(item_path, os.path.join(temp_dir, item))

    # 拷贝 resources 文件夹中的所有文件和文件夹（包含文件夹本身）
    resources_dir = os.path.join(project_root, 'resources')
    if os.path.exists(resources_dir):
        shutil.copytree(resources_dir, os.path.join(temp_dir, 'resources'))

    # 拷贝 requirements.txt
    shutil.copy(requirements_file, temp_dir)

    # Step 4: 将临时目录打包为 ZIP 文件
    # 首先打包 temp_dir 中的所有内容，但不包括 resources 文件夹
    zip_directory(zip_filename, temp_dir, base_dir=temp_dir, include_folder=False)



if __name__ == "__main__":
    create_deployment_package()
