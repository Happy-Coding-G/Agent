#### Neo4j

##### 创建语句

###### 创建节点

```
CREATE (变量名)
```

创建多个节点

```
CREATE (变量名1),(变量名2)
```

创建带标签和属性的节点（标签用于对节点进行分组，属性用于描述节点）

```
CREATE (变量名：标签{属性键：属性值})
```

###### 创建关系

```
CREATE (node1)-[:RelationshipType]->(node2) 
```

在现有节点间创建关系

```
MATCH (a:LabeofNode1), (b:LabeofNode2) 
   WHERE a.name = "nameofnode1" AND b.name = " nameofnode2" 
CREATE (a)-[: Relation]->(b) 
RETURN a,b 
```

使用标签和属性创建关系

```
CREATE (node1)-[label:Rel_Type {key1:value1, key2:value2, . . . n}]-> (node2)
```

###### Match子句

```
MATCH (n) RETURN (n) // 查询所有节点
```

```
MATCH (node:label) RETURN (node) // 获取特定标签下的节点
```

```
MATCH (node:label)<-[: Relationship]-(n)  // 根据关系检索节点
RETURN n 
```

```
MATCH (n) detach delete (n) // 删除所有节点
```

