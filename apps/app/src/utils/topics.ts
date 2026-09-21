// 多主题中文名直接来自后端 topic_labels；标签缺失回退主题 key
// list 与 reader 共用
export function topicTags(r: { topics?: string[]; topic_labels?: string[] }): string[] {
  const labels = r.topic_labels || [];
  return (r.topics || []).map((k, i) => labels[i] || k);
}
