###### Git

Git 空间的4层结构：

- 工作区：编程环境；
- 缓存区（index）；
- 本地仓库；
- 远程仓库。

Git 命令

初始化本地仓库：

```
git init
```

查看仓库的状态：

```
git status
```

添加修改文件至缓存区：红色代表未添加至缓存区，绿色代表已添加至缓存区

```
git add file_name
```

提交修改至本地仓库：

```
git commit -m "修改说明"
```

提交本地仓库至远程仓库：

```
git push origin main  将本地的 main 分支推送到名为 origin 的远程仓库的 main 分支 ( 一次 )
```

```
git push -u origin main 在推送代码的同时，将本地 main 分支与远程 origin/main 分支关联起来，后续使用 git push 即可
```

拉取远程仓库至本地

```
git pull origin main
```

```
git pull origin main --rebase 
```

从本地仓库删除文件夹

```
git rm -r --cached folder_name 
(--cache)参数表示只从 Git 索引中移除，保留本地文件
```

从本地仓库删除文件夹

```
git rm --cached file_name
```

