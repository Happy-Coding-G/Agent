-- 默认用户初始化脚本
-- 执行此脚本将创建一个默认用户、认证信息和空间

-- 1. 创建默认用户
INSERT INTO users (user_key, display_name, created_at)
VALUES ('default_user', '默认用户', NOW())
ON DUPLICATE KEY UPDATE display_name = '默认用户';

-- 获取刚创建的用户ID
SET @user_id = LAST_INSERT_ID();

-- 2. 创建默认用户认证信息（用户名: admin, 密码: admin123）
-- 注意：实际生产环境应使用 bcrypt 等加密方式存储密码
-- 这里使用简单的哈希示例，实际应使用更安全的加密方式
INSERT INTO user_auth (user_id, identity_type, identifier, credential, verified)
VALUES (@user_id, 'password', 'admin', 'admin123', 1)
ON DUPLICATE KEY UPDATE credential = 'admin123';

-- 3. 创建默认空间
INSERT INTO spaces (public_id, name, owner_user_id, created_at, updated_at)
VALUES ('default_space', '默认工作空间', @user_id, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = '默认工作空间';

-- 查询创建的信息
SELECT '用户信息' AS info_type, id, user_key, display_name, created_at FROM users WHERE user_key = 'default_user';
SELECT '认证信息' AS info_type, id, user_id, identity_type, identifier, verified FROM user_auth WHERE identifier = 'admin';
SELECT '空间信息' AS info_type, id, public_id, name, owner_user_id, created_at FROM spaces WHERE public_id = 'default_space';

-- 输出提示
SELECT '初始化完成！默认用户信息：' AS message;
SELECT '用户名: admin' AS message;
SELECT '密码: admin123' AS message;
SELECT '空间ID: default_space' AS message;