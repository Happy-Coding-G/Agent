```
查看文件内容
type 文件名
分页显示
type 文件名.扩展名 | more   
```

```
创建文件
echo 文件内容 > 文件名。扩展名
copy con 文件名.扩展名 （ctrl+z来结束编写）
```

```
删除文件
del 文件名.扩展名
删除结尾txt的所有文件
del *.txt 
删除所有文件
del *.* 
递归删除
/s 
无提示
/q 
```

```
添加隐藏属性
attrib +h 文件名 
删除隐藏属性
attrib -h 文件名 
系统级文件
+s 
无法修改
+a 
```

```
快速生成一个文件
fsutil file createnew C:
```

```
修改关联性
assoc .txt=exefile
```

```
关机倒计时
shutdown -s -t 100 
取消计时
shutdown -a 
定时重启
shutdown -r -t 100
强制
-f 
```

```
显示所有文件，包括隐藏
dir /a
```



