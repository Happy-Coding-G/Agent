/**
 * PTDS Auth API 专用查询脚本 (ESM版本)
 * 
 * 使用方法:
 *   1. 确保后端服务已启动
 *   2. 运行: node fetch-auth-api.js
 */

import http from "http";

const API_BASE = process.env.API_BASE || "http://127.0.0.1:8000";

async function request(path, method = "GET") {
  return new Promise((resolve, reject) => {
    const url = new URL(path, API_BASE);
    
    const options = {
      hostname: url.hostname,
      port: url.port || 80,
      path: url.pathname + url.search,
      method,
      headers: {
        "Accept": "application/json",
      },
      timeout: 5000,
    };

    const req = http.request(options, (res) => {
      let data = "";
      res.on("data", chunk => data += chunk);
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(data) });
        } catch {
          resolve({ status: res.statusCode, data });
        }
      });
    });

    req.on("error", reject);
    req.setTimeout(5000, () => {
      req.destroy();
      reject(new Error("Timeout"));
    });

    req.end();
  });
}

async function main() {
  console.log("\n🔐 PTDS Auth API 查询\n");
  console.log(`📡 ${API_BASE}\n`);

  try {
    // 获取 OpenAPI 文档
    console.log("📥 获取 API 文档...");
    const { data: openapi } = await request("/openapi.json");
    
    // 过滤 Auth 相关接口
    console.log("\n📋 Auth 相关接口:\n");
    
    const authPaths = {};
    for (const [path, methods] of Object.entries(openapi.paths || {})) {
      if (path.startsWith("/auth") || path.startsWith("/api/v1/auth")) {
        authPaths[path] = methods;
      }
    }
    
    if (Object.keys(authPaths).length === 0) {
      console.log("   未找到 Auth 相关接口");
    } else {
      for (const [path, methods] of Object.entries(authPaths)) {
        for (const [method, details] of Object.entries(methods)) {
          console.log(`   ${method.toUpperCase().padEnd(8)} ${path}`);
          console.log(`   └─ ${details.summary || "无描述"}\n`);
        }
      }
    }

    // 尝试调用登录接口（获取参数结构）
    console.log("🔍 登录接口参数结构:\n");
    
    if (openapi.paths["/api/v1/auth/login"]) {
      const loginSpec = openapi.paths["/api/v1/auth/login"].post;
      
      console.log("   POST /api/v1/auth/login");
      console.log("   参数:");
      
      if (loginSpec.requestBody?.content?.["application/json"]?.schema?.properties) {
        const props = loginSpec.requestBody.content["application/json"].schema.properties;
        for (const [name, prop] of Object.entries(props)) {
          console.log(`     - ${name}: ${prop.type || "any"} ${prop.description ? `// ${prop.description}` : ""}`);
        }
      }
      
      console.log("\n   响应示例:");
      if (loginSpec.responses) {
        for (const [status, resp] of Object.entries(loginSpec.responses)) {
          console.log(`     - ${status}: ${resp.description}`);
        }
      }
    }

    // Space 接口
    console.log("\n📋 Space 相关接口:\n");
    
    const spacePaths = {};
    for (const [path, methods] of Object.entries(openapi.paths || {})) {
      if (path.startsWith("/spaces") || path.startsWith("/api/v1/spaces")) {
        spacePaths[path] = methods;
      }
    }
    
    if (Object.keys(spacePaths).length === 0) {
      console.log("   未找到 Space 相关接口");
    } else {
      for (const [path, methods] of Object.entries(spacePaths)) {
        for (const [method, details] of Object.entries(methods)) {
          console.log(`   ${method.toUpperCase().padEnd(8)} ${path}`);
          console.log(`   └─ ${details.summary || "无描述"}\n`);
        }
      }
    }

    console.log("✅ 查询完成!\n");
    
  } catch (error) {
    console.error(`\n❌ 错误: ${error.message}`);
    console.log("\n💡 请确保后端服务已启动: python main.py\n");
  }
}

main();
