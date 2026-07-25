export async function getServerSideProps() {
  return {
    redirect: {
      destination: "/index.html?deployment=static-review",
      permanent: false,
    },
  };
}

export default function PublicReviewEntry() {
  return (
    <main lang="zh-CN" style={{ fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
      <h1>接班彩排</h1>
      <p>正在进入公开评审版……</p>
      <a href="./index.html?deployment=static-review">继续</a>
    </main>
  );
}
