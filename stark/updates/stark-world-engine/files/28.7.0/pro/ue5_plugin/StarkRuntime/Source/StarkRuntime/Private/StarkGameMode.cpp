// Stark World Engine Runtime - game mode + Canvas HUD (see StarkGameMode.h).
// AHUD::DrawText / DrawRect / GetTextSize / Project:
//   https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/AHUD
// FTimerManager::SetTimerForNextTick: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/FTimerManager/SetTimerForNextTick
#include "StarkGameMode.h"
#include "StarkGameSubsystem.h"
#include "StarkRules.h"
#include "StarkCharacter.h"
#include "StarkEnemy.h"
#include "StarkNpc.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "TimerManager.h"

static UStarkGameSubsystem* StarkSubM(const UObject* Ctx)
{
	const UWorld* W = Ctx ? Ctx->GetWorld() : nullptr;
	UGameInstance* GI = W ? W->GetGameInstance() : nullptr;
	return GI ? GI->GetSubsystem<UStarkGameSubsystem>() : nullptr;
}

AStarkGameMode::AStarkGameMode()
{
	PrimaryActorTick.bCanEverTick = true;
	DefaultPawnClass = AStarkPlayerCharacter::StaticClass();
	HUDClass = AStarkHUD::StaticClass();
}

void AStarkGameMode::BeginPlay()
{
	Super::BeginPlay();
	// wait one tick so every placed Stark World Engine actor has registered itself before the level starts its quests
	GetWorldTimerManager().SetTimerForNextTick(this, &AStarkGameMode::NotifyLevelReady);
}

void AStarkGameMode::NotifyLevelReady()
{
	if (UStarkGameSubsystem* G = StarkSubM(this)) { G->LevelReady(GetWorld()); }
}

void AStarkGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (UStarkGameSubsystem* G = StarkSubM(this)) { G->Tick(DeltaSeconds); }
}

// ---------------------------------------------------------------- HUD
static const FLinearColor GGold(1.f, 0.65f, 0.13f);
static const FLinearColor GMint(0.11f, 0.65f, 0.47f);
static const FLinearColor GText(0.92f, 0.89f, 0.84f);
static const FLinearColor GMuted(0.36f, 0.44f, 0.52f);

void AStarkHUD::ShowBigText(const FString& Title, const FString& Subtitle, float Seconds)
{
	BigTitle = Title;
	BigSub = Subtitle;
	BigT = Seconds;
}

void AStarkHUD::SetBossBar(const FString& Name, float Fraction)
{
	BossName = Name;
	BossFraction = Fraction;
}

void AStarkHUD::AddToast(const FString& Message, const FString& Kind)
{
	if (Toasts.Num() > 0 && Toasts.Last().Key == Message) { return; }
	Toasts.Emplace(Message, 3.2f);
	while (Toasts.Num() > 4) { Toasts.RemoveAt(0); }
}

void AStarkHUD::Panel(float X, float Y, float W, float H)
{
	DrawRect(FLinearColor(0.004f, 0.006f, 0.01f, 0.72f), X, Y, W, H);
}

float AStarkHUD::Line(const FString& Text, float X, float Y, const FLinearColor& Color, float Scale, bool bLarge)
{
	UFont* Font = bLarge ? GEngine->GetLargeFont() : GEngine->GetMediumFont();
	DrawText(Text, Color, X, Y, Font, Scale);
	float W = 0.f, H = 0.f;
	GetTextSize(Text, W, H, Font, Scale);
	return H;
}

void AStarkHUD::DrawHUD()
{
	Super::DrawHUD();
	UStarkGameSubsystem* G = StarkSubM(this);
	if (!G || !G->Rules || !Canvas) { return; }
	UStarkRules* R = G->Rules;
	const double Now = GetWorld()->GetTimeSeconds();
	const float Dt = LastTime > 0.0 ? (float)(Now - LastTime) : 0.f;
	LastTime = Now;
	const float Cw = Canvas->ClipX;
	const float Ch = Canvas->ClipY;
	const FStarkStats St = R->Stats();
	const FStarkLevelDef L = G->GetLevelDef(G->GetLevelIndex());

	// status panel
	Panel(12.f, 12.f, 290.f, 104.f);
	Line(FString::Printf(TEXT("Lv %d    HP %d/%d    %d gold"), R->Lvl, FMath::CeilToInt(R->Hp), St.MaxHp, R->Gold), 24.f, 18.f, GText);
	DrawRect(FLinearColor(1.f, 1.f, 1.f, 0.12f), 24.f, 46.f, 266.f, 9.f);
	DrawRect(FLinearColor(1.f, 0.07f, 0.16f), 24.f, 46.f, 266.f * FMath::Clamp(R->Hp / FMath::Max(1, St.MaxHp), 0.f, 1.f), 9.f);
	DrawRect(FLinearColor(1.f, 1.f, 1.f, 0.12f), 24.f, 59.f, 266.f, 6.f);
	DrawRect(GMint, 24.f, 59.f, 266.f * FMath::Clamp((float)R->Xp / FMath::Max(1, R->XpNeed()), 0.f, 1.f), 6.f);
	Line(FString::Printf(TEXT("ATK %d   DEF %d   %s"), St.Atk, St.Def, *L.Name), 24.f, 70.f, GMuted, 0.85f);
	FString Abilities;
	for (const FStarkAbilityDef& A : R->Def.Rules.Abilities)
	{
		Abilities += FString::Printf(TEXT("%s %s%s   "), *A.Key, *A.Name, R->Lvl >= A.Level ? TEXT("") : *FString::Printf(TEXT(" (lv %d)"), A.Level));
	}
	Line(Abilities, 24.f, 90.f, GMint, 0.75f);

	// quest tracker
	const TArray<FString> T = G->TrackerLines();
	if (T.Num() > 0)
	{
		Panel(Cw - 372.f, 12.f, 360.f, 22.f + T.Num() * 22.f);
		for (int32 i = 0; i < T.Num(); ++i) { Line(T[i], Cw - 360.f, 20.f + i * 22.f, i % 2 == 0 ? GGold : GText, 0.9f); }
	}

	// toasts
	for (int32 i = Toasts.Num() - 1; i >= 0; --i)
	{
		Toasts[i].Value -= Dt;
		if (Toasts[i].Value <= 0.f) { Toasts.RemoveAt(i); }
	}
	for (int32 i = 0; i < Toasts.Num(); ++i)
	{
		float W = 0.f, H = 0.f;
		GetTextSize(Toasts[i].Key, W, H, GEngine->GetMediumFont(), 1.f);
		Panel(Cw * 0.5f - W * 0.5f - 14.f, 78.f + i * 36.f, W + 28.f, 30.f);
		Line(Toasts[i].Key, Cw * 0.5f - W * 0.5f, 82.f + i * 36.f, GText);
	}

	// NPC markers and boss bar
	AStarkPlayerCharacter* Pl = G->GetPlayer();
	for (UStarkNpcComponent* N : G->Npcs())
	{
		const FString Mark = N->Marker();
		if (Mark.IsEmpty() || !N->GetOwner()) { continue; }
		const FVector S = Project(N->GetOwner()->GetActorLocation() + FVector(0.f, 0.f, 160.f));
		if (S.Z > 0.f) { Line(Mark, S.X - 6.f, S.Y - 20.f, GGold, 1.6f, true); }
	}
	BossFraction = -1.f;
	if (Pl)
	{
		for (AStarkEnemyCharacter* E : G->Enemies())
		{
			if (E->IsBoss() && E->State == TEXT("chase") && FVector::Dist2D(E->GetActorLocation(), Pl->GetActorLocation()) < E->Def.Sight * 170.f)
			{
				BossName = E->Title();
				BossFraction = E->Hp / FMath::Max(1.f, E->MaxHp);
			}
		}
	}
	if (BossFraction >= 0.f)
	{
		Panel(Cw * 0.5f - 230.f, 14.f, 460.f, 48.f);
		Line(BossName, Cw * 0.5f - 218.f, 18.f, FLinearColor(1.f, 0.6f, 0.8f));
		DrawRect(FLinearColor(1.f, 1.f, 1.f, 0.12f), Cw * 0.5f - 218.f, 44.f, 436.f, 10.f);
		DrawRect(FLinearColor(0.45f, 0.01f, 0.35f), Cw * 0.5f - 218.f, 44.f, 436.f * BossFraction, 10.f);
	}

	// interaction prompt
	if (Pl && !G->IsBusy())
	{
		FString Prompt;
		if (Pl->NearestInteractable(Prompt) && !Prompt.IsEmpty())
		{
			const FString P = TEXT("[E]  ") + Prompt;
			float W = 0.f, H = 0.f;
			GetTextSize(P, W, H, GEngine->GetMediumFont(), 1.f);
			Panel(Cw * 0.5f - W * 0.5f - 14.f, Ch - 160.f, W + 28.f, 32.f);
			Line(P, Cw * 0.5f - W * 0.5f, Ch - 156.f, GText);
		}
	}

	// big title
	if (BigT > 0.f)
	{
		BigT -= Dt;
		float W = 0.f, H = 0.f;
		GetTextSize(BigTitle, W, H, GEngine->GetLargeFont(), 2.f);
		Line(BigTitle, Cw * 0.5f - W * 0.5f, Ch * 0.32f, GText, 2.f, true);
		GetTextSize(BigSub, W, H, GEngine->GetMediumFont(), 1.f);
		Line(BigSub, Cw * 0.5f - W * 0.5f, Ch * 0.32f + 70.f, GText);
	}

	// dialogue
	if (R->bDialogueOpen)
	{
		const float Pw = FMath::Min(760.f, Cw - 40.f);
		const float Px = Cw * 0.5f - Pw * 0.5f;
		TArray<FString> Lines;
		FString Cur;
		TArray<FString> Words;
		R->Line.ParseIntoArray(Words, TEXT(" "));
		for (const FString& Wd : Words)
		{
			const FString Try = Cur.IsEmpty() ? Wd : Cur + TEXT(" ") + Wd;
			float W = 0.f, H = 0.f;
			GetTextSize(Try, W, H, GEngine->GetMediumFont(), 1.f);
			if (W > Pw - 40.f && !Cur.IsEmpty()) { Lines.Add(Cur); Cur = Wd; } else { Cur = Try; }
		}
		if (!Cur.IsEmpty()) { Lines.Add(Cur); }
		const float Ph = 44.f + Lines.Num() * 24.f + R->VisibleChoices.Num() * 28.f + 12.f;
		Panel(Px, Ch - Ph - 18.f, Pw, Ph);
		float Y = Ch - Ph - 10.f;
		Line(R->Speaker, Px + 18.f, Y, GGold);
		Y += 28.f;
		for (const FString& Ln : Lines) { Line(Ln, Px + 18.f, Y, GText); Y += 24.f; }
		for (int32 i = 0; i < R->VisibleChoices.Num(); ++i)
		{
			Line(FString::Printf(TEXT("%d   %s"), i + 1, *R->VisibleChoices[i].Text), Px + 30.f, Y + 4.f, GMint);
			Y += 28.f;
		}
	}

	// modals
	const FString Modal = G->GetModal();
	if (!Modal.IsEmpty())
	{
		TArray<TPair<FString, FLinearColor>> Rows;
		if (Modal == TEXT("quests"))
		{
			Rows.Emplace(TEXT("Quest log  (L closes)"), GGold);
			for (const FStarkQuestDef& Q : R->Def.Quests)
			{
				const FStarkQuestProgress* P = R->Quests.Find(Q.Id);
				if (!P) { continue; }
				const bool bDone = P->State == TEXT("done");
				Rows.Emplace(Q.Title + (bDone ? TEXT("  (done)") : TEXT("")), bDone ? GMint : GGold);
				for (int32 i = 0; i < Q.Steps.Num(); ++i)
				{
					const bool bOk = bDone || i < P->Step;
					Rows.Emplace(FString(bOk ? TEXT("   [x] ") : TEXT("   [ ] ")) + R->StepText(Q.Steps[i]), bOk ? GMint : (i == P->Step ? GText : GMuted));
				}
			}
			if (Rows.Num() == 1) { Rows.Emplace(TEXT("No quests yet. Look for a gold ! and press E."), GText); }
		}
		else if (Modal == TEXT("bag"))
		{
			Rows.Emplace(FString::Printf(TEXT("Bag  (I closes, 1-9 use)   ATK %d  DEF %d  Max HP %d  %d gold"), St.Atk, St.Def, St.MaxHp, R->Gold), GGold);
			TArray<FString> Ids;
			R->Inventory.GetKeys(Ids);
			for (int32 i = 0; i < Ids.Num(); ++i)
			{
				const FStarkItemDef It = R->GetItem(Ids[i]);
				const FString* Eq = R->Equipped.Find(It.Slot);
				Rows.Emplace(FString::Printf(TEXT("%d  %s x%d%s - %s"), i + 1, *It.Name, R->Inventory[Ids[i]], (Eq && *Eq == Ids[i]) ? TEXT(" (equipped)") : TEXT(""), *It.Desc), GText);
			}
			if (Ids.Num() == 0) { Rows.Emplace(TEXT("Empty. Open chests and pick things up."), GText); }
		}
		else
		{
			Rows.Emplace(TEXT("Paused  (Esc resumes)"), GGold);
			for (int32 i = 1; i <= 3; ++i)
			{
				const FString Info = G->SlotInfo(FString::FromInt(i));
				Rows.Emplace(FString::Printf(TEXT("%d save / %d load  - slot %d  %s"), i, i + 3, i, Info.IsEmpty() ? TEXT("(empty)") : *Info), GText);
			}
			const FString Auto = G->SlotInfo(TEXT("auto"));
			Rows.Emplace(FString::Printf(TEXT("7 load autosave  %s"), Auto.IsEmpty() ? TEXT("(empty)") : *Auto), GText);
			Rows.Emplace(TEXT("WASD move  Space jump  J attack  E talk  1-4 answer  H potion  Shift dash  K whirl  F bolt  L quests  I bag"), GMuted);
		}
		const float Mw = FMath::Min(820.f, Cw - 40.f);
		const float Mh = 24.f + Rows.Num() * 24.f;
		Panel(Cw * 0.5f - Mw * 0.5f, Ch * 0.5f - Mh * 0.5f, Mw, Mh);
		for (int32 i = 0; i < Rows.Num(); ++i)
		{
			Line(Rows[i].Key, Cw * 0.5f - Mw * 0.5f + 18.f, Ch * 0.5f - Mh * 0.5f + 12.f + i * 24.f, Rows[i].Value, 0.9f);
		}
	}
}
