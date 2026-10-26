// Extensões do Cytoscape que não publicam tipos próprios.
declare module "cytoscape-fcose" {
  const ext: (cy: unknown) => void;
  export default ext;
}
declare module "cytoscape-expand-collapse" {
  const ext: (cy: unknown) => void;
  export default ext;
}
