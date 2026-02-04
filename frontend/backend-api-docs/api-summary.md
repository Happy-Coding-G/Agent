# dataspace

> Version: 1.0
> 

## 接口概览

| 方法 | 路径 | 描述 | 标签 |
|------|------|------|------|
| GET | `/api/v1/healthz` | Healthz | health |
| POST | `/api/v1/auth/register` | Register | auth, Authentication |
| POST | `/api/v1/auth/login` | Login | auth, Authentication |
| POST | `/api/v1/spaces/{space_id}/folders` | Create Folder | upload, File Management |
| POST | `/api/v1/spaces/{space_id}/files/upload-init` | Init Upload | upload, File Management |
| POST | `/api/v1/spaces/{space_id}/files/upload-complete` | Complete Upload | upload, File Management |
| GET | `/api/v1/spaces/{space_id}/files/{file_public_id}/view` | Get File Content | upload, File Management |
| PATCH | `/api/v1/spaces/{space_id}/folders/{folder_public_id}/rename` | Rename Folder | upload, File Management |
| PATCH | `/api/v1/spaces/{space_id}/files/{file_public_id}/rename` | Rename File | upload, File Management |
| GET | `/api/v1/spaces/{space_id}/tree` | Get Space Tree | upload, File Management |
| GET | `/api/v1/spaces` | Get Spaces | space, Spaces |
| POST | `/api/v1/spaces` | Create Space | space, Spaces |
| DELETE | `/api/v1/spaces/{spaceId}` | Delete Space | space, Spaces |
| POST | `/api/v1/spaces/{spaceId}/switch` | Switch Space | space, Spaces |

## 接口详情

### Authentication

#### POST /api/v1/auth/register

**Register**



**响应:**

- `201`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/auth/login

**Login**



**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

### File Management

#### POST /api/v1/spaces/{space_id}/folders

**Create Folder**

创建目录：自动计算 path_cache
路径规则：/根目录/子目录

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |

**响应:**

- `201`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces/{space_id}/files/upload-init

**Init Upload**

初始化上传：生成预签名地址

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |
| folder_id | query | integer | 是 | - |
| filename | query | string | 是 | - |
| size_bytes | query | integer | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces/{space_id}/files/upload-complete

**Complete Upload**

确认上传完成：同步元数据至 files 和 file_versions

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| upload_id | query | string | 是 | - |
| object_key | query | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### GET /api/v1/spaces/{space_id}/files/{file_public_id}/view

**Get File Content**

获取文件的临时查看/下载链接

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| file_public_id | path | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### PATCH /api/v1/spaces/{space_id}/folders/{folder_public_id}/rename

**Rename Folder**

重命名目录：不仅更新自身，还需递归更新所有子目录的 path_cache

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |
| folder_public_id | path | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### PATCH /api/v1/spaces/{space_id}/files/{file_public_id}/rename

**Rename File**

重命名文件

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |
| file_public_id | path | string | 是 | - |
| new_name | query | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### GET /api/v1/spaces/{space_id}/tree

**Get Space Tree**

获取指定空间的完整目录树
算法逻辑：
1. 一次性查询空间下所有 Folder 和 File
2. 使用内存映射表（Map）将扁平数据组装成递归嵌套结构

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

### Spaces

#### GET /api/v1/spaces

**Get Spaces**

获取当前用户拥有的所有空间，支持分页

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| limit | query | integer | 否 | - |
| offset | query | integer | 否 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces

**Create Space**

创建新空间并确保事务完整性

**响应:**

- `201`: Successful Response
- `422`: Validation Error

---

#### DELETE /api/v1/spaces/{spaceId}

**Delete Space**

物理/逻辑删除空间，并检查最小保留约束

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| spaceId | path | string | 是 | - |

**响应:**

- `204`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces/{spaceId}/switch

**Switch Space**

切换当前活跃空间。
在分布式架构中，此处通常需要更新 Redis 中的 'current_space_id' 映射。

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| spaceId | path | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

### auth

#### POST /api/v1/auth/register

**Register**



**响应:**

- `201`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/auth/login

**Login**



**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

### health

#### GET /api/v1/healthz

**Healthz**



**响应:**

- `200`: Successful Response

---

### space

#### GET /api/v1/spaces

**Get Spaces**

获取当前用户拥有的所有空间，支持分页

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| limit | query | integer | 否 | - |
| offset | query | integer | 否 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces

**Create Space**

创建新空间并确保事务完整性

**响应:**

- `201`: Successful Response
- `422`: Validation Error

---

#### DELETE /api/v1/spaces/{spaceId}

**Delete Space**

物理/逻辑删除空间，并检查最小保留约束

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| spaceId | path | string | 是 | - |

**响应:**

- `204`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces/{spaceId}/switch

**Switch Space**

切换当前活跃空间。
在分布式架构中，此处通常需要更新 Redis 中的 'current_space_id' 映射。

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| spaceId | path | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

### upload

#### POST /api/v1/spaces/{space_id}/folders

**Create Folder**

创建目录：自动计算 path_cache
路径规则：/根目录/子目录

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |

**响应:**

- `201`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces/{space_id}/files/upload-init

**Init Upload**

初始化上传：生成预签名地址

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |
| folder_id | query | integer | 是 | - |
| filename | query | string | 是 | - |
| size_bytes | query | integer | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### POST /api/v1/spaces/{space_id}/files/upload-complete

**Complete Upload**

确认上传完成：同步元数据至 files 和 file_versions

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| upload_id | query | string | 是 | - |
| object_key | query | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### GET /api/v1/spaces/{space_id}/files/{file_public_id}/view

**Get File Content**

获取文件的临时查看/下载链接

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| file_public_id | path | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### PATCH /api/v1/spaces/{space_id}/folders/{folder_public_id}/rename

**Rename Folder**

重命名目录：不仅更新自身，还需递归更新所有子目录的 path_cache

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |
| folder_public_id | path | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### PATCH /api/v1/spaces/{space_id}/files/{file_public_id}/rename

**Rename File**

重命名文件

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |
| file_public_id | path | string | 是 | - |
| new_name | query | string | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

#### GET /api/v1/spaces/{space_id}/tree

**Get Space Tree**

获取指定空间的完整目录树
算法逻辑：
1. 一次性查询空间下所有 Folder 和 File
2. 使用内存映射表（Map）将扁平数据组装成递归嵌套结构

**参数:**

| 名称 | 位置 | 类型 | 必填 | 描述 |
|------|------|------|------|------|
| space_id | path | integer | 是 | - |

**响应:**

- `200`: Successful Response
- `422`: Validation Error

---

