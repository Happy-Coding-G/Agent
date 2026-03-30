#### UV 使用教程

##### 标志工作流

1、进入项目目录；

2、创建虚拟环境，生成 .venv文件：

```
uv venv
```

3、安装依赖：

requirements.txt

```
uv pip install -r requirements.txt
```

 pyproject.toml

```
uv sync
```

4、运行项目：

```
uv run python .py
```

##### 常用命令

1、删除环境：

```
rm -rf .venv
```

2、查看当前的 python：

```
uv run python -V
```

3、查看解释器路径：

```
uv run python -c "import sys;print(sys.executable)"
```

