CSS_HTML_TEMPLATE = """
<style>
  html {
background : /*Base*/ !important;
}
  body {
padding: 4px;
}
  blockquote, pre {
background : /*Base*/ !important;
color: /*Text*/  !important;
padding: 10px !important;
margin: 0px !important;
}
  pre {
background: linear-gradient(to left, #2a2d2e, #1e1e1e) !important;
color: GhostWhite !important;
}
  code {
}
  code pre {
}
  p {
color: /*Text*/  !important;
font-size: 100%;
}
  ul, li, ol {
color: /*Text*/  !important;
font-size: 100%;
padding: 3px;
margin-left: 5px;
}
  strong, b {
color: /*Text2*/  !important;
font-size: 120%;
}
  em, i {
color: /*Text*/  !important;
font-size: 110%;
}
  a, img {
background: linear-gradient(to right, /*Danger*/, /*Base1*/) !important;
border: 1px outset /*Danger*/ !important;
border-radius: 15px;
color: /*Text*/  !important;
padding: 5px;
margin: 2px 2px 2px 2px;
}
  a:hover, img:hover {
background: linear-gradient(to left, /*Danger*/, /*Base1*/) !important;
color: /*Text2*/  !important;
padding: 5px;
}
  h1 {
background: linear-gradient(to left, /*Danger*/, /*Base1*/) !important;
color: /*Accent*/  !important;
text-align: center;
border: 2px outset /*Danger*/ !important; border-radius: 50px;
font-size: 160%; font-weight: bolder;
padding: 10px;
}
  h2 {
background: linear-gradient(to right, /*Danger*/, /*Base1*/) !important;
color: /*Text*/  !important;
border: 3px groove /*Warning*/ !important; border-radius: 0px 20px 10px 20px;
font-size: 140%;
font-weight: bold;
padding: 10px;
}
  h3 {
background: /*Base1*/  !important;
color: /*Text*/  !important;
border: 2px ridge /*Warning*/ !important; border-radius: 0px 15px 0px 15px;
font-size: 130% ; font-weight: bolder ;
margin-left : 20px;
padding: 5px;
}
  h4 {
background: /*Base*/  !important;
color: /*Text2*/  !important;
border-bottom: 6px ridge /*Warning*/ !important; border-radius: 0px 0px 0px 15px;
font-size: 120% !important; font-weight: bolder ;
margin-left : 40px;
padding: 4px;
}
  h5 {
background: /*Base*/  !important;
color: /*Text*/  !important;
border-left: 6px outset /*Warning*/ !important; border-radius: 0px 0px 0px 15px;
font-size: 110% !important; font-weight: bolder ;
margin-left : 60px;
padding: 3px;
}
  h6 {
background: /*Base*/  !important;
color: /*Text*/  !important;
border-left: 6px outset /*Danger*/ !important;
font-size: 105% !important; font-weight: bolder ;
margin-left : 80px;
padding: 3px;
}
  table, th, td {
background: /*Base*/  !important;
color: /*Text*/  !important;
border-collapse: collapse;
width: auto !important;
padding: 4px;
}
  th {
background: /*Base1*/  !important;
border: 2px solid /*Warning*/ !important;
color : /*Text2*/  !important;
}
  td:not(:has(pre)) {
border: 2px solid /*Warning*/ !important;
background:linear-gradient(to left, /*Base*/, /*Base1*/) !important;
}
  td:has(pre) {
border: 1px solid /*Warning*/ !important;
background: transparent !important;
padding: 0 !important;
}
  hr {
background:linear-gradient(to right, /*Danger*/, /*Warning*/) !important;
}
  llm {
background: linear-gradient(to right, /*Danger*/, /*Base1*/) !important;
color: /*Accent*/  !important;
border-left: 12px double /*Text2*/ !important; border-radius: 5px;
font-size: 200% ;
font-weight: bolder !important;
padding: 10px;
margin: 20px;
text-align: left;
}
  role {
color: /*Warning*/ !important;
font-size: 120% ;
font-style:italic;
}
  date {
color: /*Text2*/ !important;
font-weight: normal !important;
}
</style>
    """

CSS_MD_TEMPLATE = """
<style>
  body {
background : /*Base*/ !important;
}
  blockquote, pre {
background : /*Base*/ !important;
border: 1px solid /*Warning*/ !important;
color: /*Text*/  !important;
padding: 8px 8px 8px 8px !important;
margin: 5px 5px 5px 5px !important;
}
  pre {
background: linear-gradient(to left, #2a2d2e, #1e1e1e) !important;
color: GhostWhite !important;
}
  code {
}
  code pre {
}
  p {
color: /*Text*/  !important;
font-size: 100%;
}
  ul, li, ol {
color: /*Text*/  !important;
font-size: 100%;
padding: 3px;
}
  strong, b {
color: /*Text2*/  !important;
font-size: 120%;
}
  em, i {
color: /*Text*/  !important;
font-size: 110%;
}
  a, img {
background: linear-gradient(to right, /*Danger*/, /*Base1*/) !important;
border: 1px outset /*Danger*/ !important;
border-radius: 15px;
color: /*Text*/  !important;
padding: 5px;
margin: 2px 2px 2px 2px;
}
  a:hover, img:hover {
background: linear-gradient(to left, /*Danger*/, /*Base1*/) !important;
color: /*Text2*/  !important;
padding: 5px;
}
  h1 {
background: linear-gradient(to left, /*Danger*/, /*Base1*/) !important;
color: /*Accent*/  !important;
text-align: center;
border: 2px outset /*Danger*/ !important; border-radius: 50px;
font-size: 160%; font-weight: bolder;
padding: 10px;
}
  h2 {
background: linear-gradient(to right, /*Danger*/, /*Base1*/) !important;
color: /*Text*/  !important;
border: 3px groove /*Warning*/ !important; border-radius: 0px 20px 10px 20px;
font-size: 140%;
font-weight: bold;
padding: 10px;
}
  h3 {
background: /*Base1*/  !important;
color: /*Text*/  !important;
border: 2px ridge /*Warning*/ !important; border-radius: 0px 15px 0px 15px;
font-size: 130% ; font-weight: bolder ;
margin-left : 20px;
padding: 5px;
}
  h4 {
background: /*Base*/  !important;
color: /*Text2*/  !important;
border-bottom: 6px ridge /*Warning*/ !important; border-radius: 0px 0px 0px 15px;
font-size: 120% !important; font-weight: bolder ;
margin-left : 40px;
padding: 4px;
}
  h5 {
background: /*Base*/  !important;
color: /*Text*/  !important;
border-left: 6px outset /*Warning*/ !important; border-radius: 0px 0px 0px 15px;
font-size: 110% !important; font-weight: bolder ;
margin-left : 60px;
padding: 3px;
}
  h6 {
background: /*Base*/  !important;
color: /*Text*/  !important;
border-left: 6px outset /*Danger*/ !important;
font-size: 105% !important; font-weight: bolder ;
margin-left : 80px;
padding: 3px;
}
  table, th, td {
background: /*Base*/  !important;
color: /*Text*/  !important;
border-collapse: collapse;
width: auto !important;
padding: 4px;
}
  th {
background: /*Base1*/  !important;
border: 2px solid /*Warning*/ !important;
color : /*Text2*/  !important;
}
  td {
border: 2px solid /*Warning*/ !important;
background:linear-gradient(to left, /*Base*/, /*Base1*/) !important;
}
  hr {
background:linear-gradient(to right, /*Danger*/, /*Warning*/) !important;
}
  llm {
background: linear-gradient(to right, /*Danger*/, /*Base1*/) !important;
color: /*Accent*/  !important;
border-left: 12px double /*Text2*/ !important; border-radius: 5px;
font-size: 200% ;
font-weight: bolder !important;
padding: 10px;
margin: 20px;
text-align: left;
}
  role {
color: /*Warning*/ !important;
font-size: 120% ;
font-style:italic;
}
  date {
color: /*Text2*/ !important;
font-weight: normal !important;
}
</style>
    """
