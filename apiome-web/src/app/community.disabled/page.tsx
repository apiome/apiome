import { getLinks } from "@/lib/links";
import type { Metadata } from "next";
import Link from "next/link";
import { MessageSquare, BookOpen, Video, Users, Github, ArrowRight, Heart } from "lucide-react";
import { Button } from "../components/ui/Button";

export const metadata: Metadata = {
  title: "Community - Apiome",
  description: "Join the Apiome community of developers building better APIs",
};

export default function CommunityPage() {
  const links = getLinks();

  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="border-b border-zinc-200 bg-gradient-to-b from-white to-zinc-50 px-6 py-16 dark:border-zinc-800 dark:from-zinc-950 dark:to-zinc-900">
        <div className="container mx-auto max-w-4xl text-center">
          <div className="mb-6 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-600">
            <Users className="h-8 w-8 text-white" />
          </div>
          <h1 className="mb-4 text-5xl font-bold text-zinc-900 dark:text-zinc-50">
            Join Our Community
          </h1>
          <p className="text-xl text-zinc-600 dark:text-zinc-400">
            Connect with developers, share knowledge, and build better APIs together
          </p>
        </div>
      </section>

      {/* Community Resources */}
      <section className="border-b border-zinc-200 px-6 py-20 dark:border-zinc-800">
        <div className="container mx-auto max-w-6xl">
          <div className="mb-16 text-center">
            <h2 className="mb-4 text-4xl font-bold text-zinc-900 dark:text-zinc-50">
              Ways to Connect
            </h2>
            <p className="text-xl text-zinc-600 dark:text-zinc-400">
              Choose how you want to engage with the community
            </p>
          </div>

          <div className="grid gap-8 md:grid-cols-2">
            {/* Discord */}
            <div className="rounded-2xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
              <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600 dark:bg-indigo-950 dark:text-indigo-400">
                <MessageSquare className="h-6 w-6" />
              </div>
              <h3 className="mb-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                Discord Community
              </h3>
              <p className="mb-6 text-zinc-600 dark:text-zinc-400">
                Join our active Discord server for real-time discussions, support, and collaboration with other developers.
              </p>
              <a
                href="https://discord.gg/apiome"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button className="w-full">
                  Join Discord
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </a>
            </div>

            {/* GitHub */}
            <div className="rounded-2xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
              <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-lg bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50">
                <Github className="h-6 w-6" />
              </div>
              <h3 className="mb-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                GitHub Discussions
              </h3>
              <p className="mb-6 text-zinc-600 dark:text-zinc-400">
                Ask questions, share ideas, and contribute to the project on GitHub. Star the repo to stay updated!
              </p>
              <a
                href="https://github.com/apiome/discussions"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button variant="outline" className="w-full">
                  View on GitHub
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </a>
            </div>

            {/* Documentation */}
            <div className="rounded-2xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
              <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-lg bg-green-100 text-green-600 dark:bg-green-950 dark:text-green-400">
                <BookOpen className="h-6 w-6" />
              </div>
              <h3 className="mb-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                Documentation
              </h3>
              <p className="mb-6 text-zinc-600 dark:text-zinc-400">
                Comprehensive guides, tutorials, and API references to help you get the most out of Apiome.
              </p>
              <a
                href="https://docs.apiome.app"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button variant="outline" className="w-full">
                  Read Docs
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </a>
            </div>

            {/* YouTube */}
            <div className="rounded-2xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
              <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-lg bg-red-100 text-red-600 dark:bg-red-950 dark:text-red-400">
                <Video className="h-6 w-6" />
              </div>
              <h3 className="mb-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
                Video Tutorials
              </h3>
              <p className="mb-6 text-zinc-600 dark:text-zinc-400">
                Watch step-by-step tutorials, feature demos, and best practices on our YouTube channel.
              </p>
              <a
                href={links.demo}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button variant="outline" className="w-full">
                  Watch Videos
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Community Stats */}
      <section className="border-b border-zinc-200 bg-zinc-50 px-6 py-16 dark:border-zinc-800 dark:bg-zinc-900/50">
        <div className="container mx-auto max-w-6xl">
          <div className="grid gap-8 md:grid-cols-4">
            <div className="text-center">
              <div className="mb-2 text-4xl font-bold text-blue-600 dark:text-blue-400">
                5k+
              </div>
              <div className="text-zinc-600 dark:text-zinc-400">
                Community Members
              </div>
            </div>
            <div className="text-center">
              <div className="mb-2 text-4xl font-bold text-purple-600 dark:text-purple-400">
                2k+
              </div>
              <div className="text-zinc-600 dark:text-zinc-400">
                GitHub Stars
              </div>
            </div>
            <div className="text-center">
              <div className="mb-2 text-4xl font-bold text-green-600 dark:text-green-400">
                100+
              </div>
              <div className="text-zinc-600 dark:text-zinc-400">
                Contributors
              </div>
            </div>
            <div className="text-center">
              <div className="mb-2 text-4xl font-bold text-orange-600 dark:text-orange-400">
                24/7
              </div>
              <div className="text-zinc-600 dark:text-zinc-400">
                Community Support
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Contributing */}
      <section className="border-b border-zinc-200 px-6 py-20 dark:border-zinc-800">
        <div className="container mx-auto max-w-4xl">
          <div className="text-center">
            <div className="mb-6 inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-pink-100 text-pink-600 dark:bg-pink-950 dark:text-pink-400">
              <Heart className="h-8 w-8" />
            </div>
            <h2 className="mb-4 text-4xl font-bold text-zinc-900 dark:text-zinc-50">
              Contribute to Apiome
            </h2>
            <p className="mb-8 text-xl text-zinc-600 dark:text-zinc-400">
              Help us make Apiome better for everyone. Contributions are always welcome!
            </p>
            <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
              <a
                href="https://github.com/apiome/apiome"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button size="lg">
                  View on GitHub
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </a>
              <a
                href="https://github.com/apiome/apiome/blob/main/CONTRIBUTING.md"
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button size="lg" variant="outline">
                  Contributing Guide
                </Button>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Community Guidelines */}
      <section className="px-6 py-20">
        <div className="container mx-auto max-w-4xl">
          <h2 className="mb-8 text-center text-3xl font-bold text-zinc-900 dark:text-zinc-50">
            Community Guidelines
          </h2>
          <div className="space-y-6 rounded-2xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
            <div>
              <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                Be Respectful
              </h3>
              <p className="text-zinc-600 dark:text-zinc-400">
                Treat everyone with respect. We're all here to learn and help each other.
              </p>
            </div>
            <div>
              <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                Stay On Topic
              </h3>
              <p className="text-zinc-600 dark:text-zinc-400">
                Keep discussions relevant to Apiome, API design, and related technologies.
              </p>
            </div>
            <div>
              <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                Help Others
              </h3>
              <p className="text-zinc-600 dark:text-zinc-400">
                Share your knowledge and experience. Everyone was a beginner once!
              </p>
            </div>
            <div>
              <h3 className="mb-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                No Spam
              </h3>
              <p className="text-zinc-600 dark:text-zinc-400">
                Self-promotion is okay in moderation, but don't spam the community.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
