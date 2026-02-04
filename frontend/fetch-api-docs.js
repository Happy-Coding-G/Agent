/**
 * PTDS API 文档查询脚本 (ESM版本)
 * 
 * 使用方法:
 *   1. 确保后端服务已启动 (http://127.0.0.1:8000)
 *   2. 运行: node fetch-api-docs.js
 * 
 * 输出:
 *   - api-docs.json: 完整的 OpenAPI 文档
 *   - api-summary.md: Markdown 格式的接口概览
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import https from "https";
import http from "http";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const API_BASE = process.env.API_BASE || "http://127.0.0.1:8000";
const OUTPUT_DIR = path.join(__dirname, "backend-api-docs");

// 解析 URL
function parseUrl(urlStr) {
  const url = new URL(urlStr);
  return {
    hostname: url.hostname,
    port: url.port,
    path: url.pathname,
    protocol: url.protocol,
  };
}

// HTTP 请求封装
async function request(urlStr, options = {}) {
  return new Promise((resolve, reject) => {
    const parsed = parseUrl(urlStr);
    
    const reqOptions = {
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === "https:" ? 443 : 80),
      path: parsed.path + (options.searchParams ? `?${options.searchParams.toString()}` : ""),
      method: options.method || "GET",
      headers: {
        "Accept": "application/json",
        ...options.headers,
      },
      timeout: 10000,
    };

    const client = parsed.protocol === "https:" ? https : http;
    
    const req = client.request(reqOptions, (res) => {
      let data = "";
      
      res.on("data", chunk => data += chunk);
      res.on("end", () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve(data);
        }
      });
    });

    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("Request timeout"));
    });

    if (options.body) {
      req.write(JSON.stringify(options.body));
    }
    
    req.end();
  });
}

// 格式化参数类型
function formatType(param) {
  const schema = param.schema || {};
  if (schema.$ref) {
    return schema.$ref.split("/").pop();
  }
  return schema.type || "any";
}

// 生成 Markdown 文档
function generateMarkdown(doc) {
  let md = `# ${doc.info.title}\n\n`;
  md += `> Version: ${doc.info.version}\n`;
  md += `> ${doc.info.description || ""}\n\n`;
  
  md += `## 接口概览\n\n`;
  md += `| 方法 | 路径 | 描述 | 标签 |\n`;
  md += `|------|------|------|------|\n`;
  
  const paths = doc.paths || {};
  const tags = new Set();
  
  for (const [path, methods] of Object.entries(paths)) {
    for (const [method, details] of Object.entries(methods)) {
      const summary = details.summary || "";
      const pathTags = details.tags || ["other"];
      pathTags.forEach(t => tags.add(t));
      md += `| ${method.toUpperCase()} | \`${path}\` | ${summary} | ${pathTags.join(", ")} |\n`;
    }
  }
  
  md += `\n## 接口详情\n\n`;
  
  for (const tag of [...tags].sort()) {
    md += `### ${tag}\n\n`;
    
    for (const [path, methods] of Object.entries(paths)) {
      for (const [method, details] of Object.entries(methods)) {
        if (!details.tags?.includes(tag)) continue;
        
        md += `#### ${method.toUpperCase()} ${path}\n\n`;
        md += `**${details.summary || ""}**\n\n`;
        md += `${details.description || ""}\n\n`;
        
        // 请求参数
        if (details.parameters?.length > 0) {
          md += `**参数:**\n\n`;
          md += `| 名称 | 位置 | 类型 | 必填 | 描述 |\n`;
          md += `|------|------|------|------|------|\n`;
          
          for (const param of details.parameters) {
            md += `| ${param.name} | ${param.in} | ${formatType(param)} | ${param.required ? "是" : "否"} | ${param.description || "-"} |\n`;
          }
          md += `\n`;
        }
        
        // 响应
        if (details.responses) {
          md += `**响应:**\n\n`;
          for (const [status, response] of Object.entries(details.responses)) {
            md += `- \`${status}\`: ${response.description}\n`;
          }
          md += `\n`;
        }
        
        md += `---\n\n`;
      }
    }
  }
  
  return md;
}

// 提取 Auth 相关接口
function extractAuthEndpoints(doc) {
  const authDoc = {
    openapi: doc.openapi,
    info: doc.info,
    paths: {},
  };
  
  const authPaths = ["/auth", "/api/v1/auth"];
  const authTags = ["Auth", "Authentication", "auth"];
  
  for (const [path, methods] of Object.entries(doc.paths || {})) {
    const isAuthPath = authPaths.some(p => path.startsWith(p));
    const isAuthTag = methods.tags?.some(t => authTags.includes(t));
    
    if (isAuthPath || isAuthTag) {
      authDoc.paths[path] = methods;
    }
  }
  
  return authDoc;
}

// 提取 Space 相关接口
function extractSpaceEndpoints(doc) {
  const spaceDoc = {
    openapi: doc.openapi,
    info: doc.info,
    paths: {},
  };
  
  const spacePaths = ["/spaces", "/space", "/api/v1/spaces"];
  const spaceTags = ["Space", "Spaces", "space"];
  
  for (const [path, methods] of Object.entries(doc.paths || {})) {
    const isSpacePath = spacePaths.some(p => path.startsWith(p));
    const isSpaceTag = methods.tags?.some(t => spaceTags.includes(t));
    
    if (isSpacePath || isSpaceTag) {
      spaceDoc.paths[path] = methods;
    }
  }
  
  return spaceDoc;
}

// 主函数
async function main() {
  console.log(`\n🚀 PTDS API 文档查询工具\n`);
  console.log(`📡 API 基础地址: ${API_BASE}`);
  
  try {
    // 确保输出目录存在
    if (!fs.existsSync(OUTPUT_DIR)) {
      fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }
    
    // 获取 OpenAPI 文档
    console.log(`\n📥 正在获取 API 文档...`);
    const openapiUrl = `${API_BASE}/openapi.json`;
    const doc = await request(openapiUrl);
    
    console.log(`✅ 获取成功!`);
    console.log(`   标题: ${doc.info?.title}`);
    console.log(`   版本: ${doc.info?.version}`);
    console.log(`   接口数量: ${Object.keys(doc.paths || {}).length}`);
    
    // 保存完整文档
    const fullDocPath = path.join(OUTPUT_DIR, "api-docs.json");
    fs.writeFileSync(fullDocPath, JSON.stringify(doc, null, 2), "utf-8");
    console.log(`\n💾 已保存: ${fullDocPath}`);
    
    // 生成 Markdown 概览
    const mdPath = path.join(OUTPUT_DIR, "api-summary.md");
    const md = generateMarkdown(doc);
    fs.writeFileSync(mdPath, md, "utf-8");
    console.log(`💾 已保存: ${mdPath}`);
    
    // 提取 Auth 接口
    const authDoc = extractAuthEndpoints(doc);
    if (Object.keys(authDoc.paths).length > 0) {
      const authDocPath = path.join(OUTPUT_DIR, "auth-api.json");
      fs.writeFileSync(authDocPath, JSON.stringify(authDoc, null, 2), "utf-8");
      console.log(`💾 已保存: ${authDocPath} (${Object.keys(authDoc.paths).length} 个接口)`);
    }
    
    // 提取 Space 接口
    const spaceDoc = extractSpaceEndpoints(doc);
    if (Object.keys(spaceDoc.paths).length > 0) {
      const spaceDocPath = path.join(OUTPUT_DIR, "space-api.json");
      fs.writeFileSync(spaceDocPath, JSON.stringify(spaceDoc, null, 2), "utf-8");
      console.log(`💾 已保存: ${spaceDocPath} (${Object.keys(spaceDoc.paths).length} 个接口)`);
    }
    
    // 输出接口统计
    console.log(`\n📊 接口统计:\n`);
    
    const tagCounts = {};
    for (const [path, methods] of Object.entries(doc.paths || {})) {
      for (const [method, details] of Object.entries(methods)) {
        const tags = details.tags || ["未分类"];
        for (const tag of tags) {
          tagCounts[tag] = (tagCounts[tag] || 0) + 1;
        }
      }
    }
    
    for (const [tag, count] of Object.entries(tagCounts).sort((a, b) => b[1] - a[1])) {
      console.log(`   ${tag}: ${count} 个接口`);
    }
    
    console.log(`\n✨ 完成!`);
    console.log(`\n📁 输出目录: ${OUTPUT_DIR}\n`);
    
  } catch (error) {
    console.error(`\n❌ 错误: ${error.message}`);
    console.log(`\n💡 提示:`);
    console.log(`   1. 确保后端服务已启动: python main.py`);
    console.log(`   2. 检查 API 地址是否正确，当前: ${API_BASE}`);
    console.log(`   3. 可以通过环境变量修改: API_BASE=http://localhost:8000 node fetch-api-docs.js\n`);
    process.exit(1);
  }
}

main();
