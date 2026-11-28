declare module "electrobun/main" {
  export const PATHS: {
    RESOURCES_FOLDER: string;
    VIEWS_FOLDER: string;
    [key: string]: string;
  };
  export const ApplicationMenu: any;
  export class BrowserWindow {
    [key: string]: any;
    constructor(options: Record<string, unknown>);
  }
  export const Screen: any;
  export const Utils: any;
  export const Updater: any;
  const electrophun: {
    events: {
      on(event: string, listener: (event: any) => void): void;
      [key: string]: any;
    };
    [key: string]: any;
  };
  export default electrophun;
}